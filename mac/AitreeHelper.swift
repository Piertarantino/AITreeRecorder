// AI Tree Recorder – helper per macOS (14 o successivo).
//
//   aitree-helper sysaudio OUT.wav   registra l'audio del Mac (gli altri della call)
//                                    con ScreenCaptureKit; si ferma con "q" o chiudendo stdin.
//                                    Stampa "READY <epoch>" quando il campione 0 corrisponde a <epoch>.
//   aitree-helper mic-users          elenca "pid<TAB>bundle id" delle app che usano il microfono
//   aitree-helper check              verifica il permesso Registrazione schermo e audio
//
// Compilazione: vedi build-mac.sh (serve solo "xcode-select --install").

import AVFoundation
import AppKit
import CoreAudio
import CoreMedia
import Foundation
import ScreenCaptureKit

setvbuf(stdout, nil, _IOLBF, 0)

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(1)
}

// MARK: - App che usano il microfono (Core Audio process objects, macOS 14+)

func propertyData<T>(_ obj: AudioObjectID, _ selector: AudioObjectPropertySelector, _ value: inout T) -> Bool {
    var addr = AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal,
                                          mElement: kAudioObjectPropertyElementMain)
    var size = UInt32(MemoryLayout<T>.size)
    return withUnsafeMutablePointer(to: &value) { AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, $0) } == noErr
}

func micUsers() {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyProcessObjectList,
                                          mScope: kAudioObjectPropertyScopeGlobal,
                                          mElement: kAudioObjectPropertyElementMain)
    let system = AudioObjectID(kAudioObjectSystemObject)
    var size: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(system, &addr, 0, nil, &size) == noErr, size > 0 else { return }
    var ids = [AudioObjectID](repeating: 0, count: Int(size) / MemoryLayout<AudioObjectID>.size)
    guard AudioObjectGetPropertyData(system, &addr, 0, nil, &size, &ids) == noErr else { return }
    for id in ids {
        var running: UInt32 = 0
        guard propertyData(id, kAudioProcessPropertyIsRunningInput, &running), running != 0 else { continue }
        var pid: pid_t = 0
        _ = propertyData(id, kAudioProcessPropertyPID, &pid)
        var bundle: CFString? = nil
        _ = propertyData(id, kAudioProcessPropertyBundleID, &bundle)
        var name = (bundle as String?) ?? ""
        if name.isEmpty {
            name = NSRunningApplication(processIdentifier: pid)?.bundleIdentifier
                ?? NSRunningApplication(processIdentifier: pid)?.localizedName ?? "pid\(pid)"
        }
        print("\(pid)\t\(name)")
    }
}

// MARK: - Audio di sistema con ScreenCaptureKit

final class SystemAudio: NSObject, SCStreamOutput, SCStreamDelegate {
    let url: URL
    var file: AVAudioFile?
    var stream: SCStream?
    let rate = 48000.0
    var startHost: Double = 0       // secondi sul clock host corrispondenti al campione 0
    var written: AVAudioFramePosition = 0
    let queue = DispatchQueue(label: "aitree.audio")

    init(url: URL) { self.url = url }

    func start() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else { fail("Nessuno schermo disponibile.") }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let cfg = SCStreamConfiguration()
        cfg.capturesAudio = true
        cfg.excludesCurrentProcessAudio = true
        cfg.sampleRate = Int(rate)
        cfg.channelCount = 1
        // Il video non serve: lo riduciamo al minimo indispensabile.
        cfg.width = 2
        cfg.height = 2
        cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        cfg.queueDepth = 3

        let fmt = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: rate, channels: 1, interleaved: false)!
        file = try AVAudioFile(forWriting: url, settings: [
            AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: rate, AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false,
        ], commonFormat: fmt.commonFormat, interleaved: false)

        let s = SCStream(filter: filter, configuration: cfg, delegate: self)
        try s.addStreamOutput(self, type: .audio, sampleHandlerQueue: queue)
        stream = s
        try await s.startCapture()
        let host = CMClockGetTime(CMClockGetHostTimeClock()).seconds
        queue.sync { startHost = host }
        print(String(format: "READY %.3f", Date().timeIntervalSince1970))
    }

    func stop() async {
        try? await stream?.stopCapture()
        queue.sync { file = nil }   // chiude e finalizza il WAV
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        FileHandle.standardError.write("Cattura interrotta: \(error.localizedDescription)\n".data(using: .utf8)!)
        file = nil
        exit(2)
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, let file, sb.isValid, let desc = sb.formatDescription,
              let asbd = desc.audioStreamBasicDescription else { return }
        guard let inFmt = AVAudioFormat(standardFormatWithSampleRate: asbd.mSampleRate,
                                        channels: AVAudioChannelCount(asbd.mChannelsPerFrame)) else { return }
        let frames = AVAudioFrameCount(sb.numSamples)
        guard frames > 0, let pcm = AVAudioPCMBuffer(pcmFormat: inFmt, frameCapacity: frames) else { return }
        pcm.frameLength = frames
        let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(sb, at: 0, frameCount: Int32(frames),
                                                                  into: pcm.mutableAudioBufferList)
        guard status == noErr, let src = pcm.floatChannelData else { return }

        // Mono: media dei canali.
        guard let out = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: frames),
              let dst = out.floatChannelData else { return }
        out.frameLength = frames
        let ch = Int(inFmt.channelCount)
        for i in 0..<Int(frames) {
            var v: Float = 0
            for c in 0..<ch { v += src[c][i] }
            dst[0][i] = v / Float(ch)
        }

        // Silenzio dove ScreenCaptureKit non ha mandato nulla: la traccia resta allineata all'orologio.
        if startHost > 0 {
            let expected = AVAudioFramePosition((sb.presentationTimeStamp.seconds - startHost) * rate)
            let gap = expected - written
            if gap > AVAudioFramePosition(rate * 0.25),
               let pad = AVAudioPCMBuffer(pcmFormat: file.processingFormat, frameCapacity: AVAudioFrameCount(gap)) {
                pad.frameLength = AVAudioFrameCount(gap)   // già a zero
                try? file.write(from: pad)
                written += gap
            }
        }
        try? file.write(from: out)
        written += AVAudioFramePosition(frames)
    }
}

// MARK: - main

var signalSources: [DispatchSourceSignal] = []
let args = CommandLine.arguments
guard args.count >= 2 else { fail("Uso: aitree-helper sysaudio OUT.wav | mic-users | check") }

switch args[1] {
case "mic-users":
    micUsers()
case "check":
    if CGPreflightScreenCaptureAccess() {
        print("ok")
    } else {
        CGRequestScreenCaptureAccess()
        fail("Consenti Registrazione schermo e audio in Impostazioni di Sistema > Privacy e sicurezza, poi riavvia.")
    }
case "sysaudio":
    guard args.count >= 3 else { fail("Indica il file WAV di uscita.") }
    let rec = SystemAudio(url: URL(fileURLWithPath: args[2]))
    Task {
        do { try await rec.start() } catch { fail("Avvio cattura non riuscito: \(error.localizedDescription)") }
    }
    // Stop: "q" su stdin, stdin chiuso, oppure SIGTERM/SIGINT.
    func finish() {
        Task { await rec.stop(); exit(0) }
    }
    for sig in [SIGINT, SIGTERM] {
        signal(sig, SIG_IGN)
        let src = DispatchSource.makeSignalSource(signal: sig, queue: .main)
        src.setEventHandler { finish() }
        src.resume()
        signalSources.append(src)
    }
    Thread.detachNewThread {
        while let line = readLine(strippingNewline: true) {
            if line.trimmingCharacters(in: .whitespaces) == "q" { break }
        }
        DispatchQueue.main.async { finish() }
    }
    dispatchMain()
default:
    fail("Comando sconosciuto: \(args[1])")
}

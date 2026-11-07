"""Punto di avvio dell'app impacchettata (installer Windows / app Mac).

Senza argomenti apre l'interfaccia; con argomenti si comporta come `python -m aitree ...`.
"""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if len(sys.argv) > 1:
        from aitree.__main__ import main
        main()
    else:
        from aitree.ui import main
        main()

"""
Assistant d'analyse de paris NBA — point d'entrée.

    python main.py                  # analyse réelle (clé The Odds API requise)
    python main.py --demo           # données fictives, sans clé ni réseau
    python main.py --show-rejected  # détaille toutes les causes de rejet
"""
from __future__ import annotations

import argparse
import logging
import sys

import config
from analyzer import build_report, save_report
from filters import FilterContext, evaluate_all


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Assistant d'analyse de paris NBA (combiné ~1.80)")
    p.add_argument("--demo", action="store_true", help="utiliser des données fictives")
    p.add_argument("--hours", type=float, default=config.LOOKAHEAD_HOURS,
                   help=f"fenêtre d'analyse en heures (défaut {config.LOOKAHEAD_HOURS})")
    p.add_argument("--show-rejected", action="store_true", help="lister toutes les causes de rejet")
    p.add_argument("--no-save", action="store_true", help="ne pas écrire le rapport dans reports/")
    p.add_argument("--html", metavar="DOSSIER", help="générer aussi le site web (ex. --html docs)")
    p.add_argument("-v", "--verbose", action="store_true", help="logs détaillés")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # accents/symboles sous Windows
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    for problem in config.validate():
        print(f"[config] {problem}")

    if args.demo:
        from demo_data import build_demo_slate
        slate = build_demo_slate()
    else:
        if not config.ODDS_API_KEY:
            print("ODDS_API_KEY manquante : crée un fichier .env (voir .env.example) "
                  "ou lance `python main.py --demo`.")
            return 1
        import requests
        from data_fetcher import DataFetcher
        try:
            slate = DataFetcher().load_slate(args.hours)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            hint = " (clé API invalide ?)" if code == 401 else " (quota épuisé ?)" if code == 429 else ""
            print(f"Erreur HTTP {code} en récupérant les données{hint} : {exc}")
            return 2
        except requests.RequestException as exc:
            print(f"Erreur réseau : {exc}")
            return 2

    if not slate.matchups:
        print("Aucun match NBA avec cotes dans la fenêtre d'analyse.")
        if args.html:
            _write_site(slate, [], args.html)
        return 0

    ctx = FilterContext(
        contenders=slate.contenders,
        contenders_source=slate.contenders_source,
        key_players=slate.key_players if slate.key_players is not None else dict(config.KEY_PLAYERS),
        now=slate.generated_at,
    )
    evaluations = evaluate_all(slate.matchups, ctx)
    report = build_report(slate, evaluations, show_rejected=args.show_rejected)
    print(report)

    if not args.no_save:
        path = save_report(report, slate.generated_at)
        print(f"\nRapport enregistré : {path}")
    if args.html:
        _write_site(slate, evaluations, args.html)
    return 0


def _write_site(slate, evaluations, out_dir: str) -> None:
    from pathlib import Path
    from web_report import write_site
    index = write_site(slate, evaluations, Path(out_dir))
    print(f"Page web générée : {index}")


if __name__ == "__main__":
    sys.exit(main())

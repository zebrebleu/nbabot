"""
Assistant d'analyse de paris NBA — point d'entrée.

    python main.py                    # prochaine nuit NBA (clé The Odds API requise)
    python main.py --date 2026-10-28  # une date précise du calendrier NBA (date américaine)
    python main.py --demo             # données fictives, sans clé ni réseau
    python main.py --html docs        # génère aussi le site web
    python main.py --show-rejected    # détaille toutes les causes de rejet
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import config
from analyzer import build_report, save_report
from filters import FilterContext, evaluate_all


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Assistant d'analyse de paris NBA")
    p.add_argument("--sport", choices=["nba", "tennis", "all"], default="nba",
                   help="sport à analyser (défaut : nba)")
    p.add_argument("--demo", action="store_true", help="utiliser des données fictives")
    p.add_argument("--date", type=date.fromisoformat, metavar="AAAA-MM-JJ",
                   help="date du calendrier NBA à analyser (défaut : prochaine nuit avec des matchs)")
    p.add_argument("--hours", type=float, help=argparse.SUPPRESS)   # ancienne option, ignorée
    p.add_argument("--force", action="store_true",
                   help="regénérer la page même si un match de la nuit a déjà commencé")
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

    codes = []
    if args.sport in ("nba", "all"):
        codes.append(run_nba(args))
    if args.sport in ("tennis", "all"):
        import tennis_main
        codes.append(tennis_main.run(demo=args.demo, html_dir=args.html))
    return max(codes)


def run_nba(args) -> int:
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
            slate = DataFetcher().load_slate(args.date)
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else "?"
            hint = " (clé API invalide ?)" if code == 401 else " (quota épuisé ?)" if code == 429 else ""
            print(f"Erreur HTTP {code} en récupérant les données{hint} : {exc}")
            return 2
        except requests.RequestException as exc:
            print(f"Erreur réseau : {exc}")
            return 2

    # Analyse figée : une fois un match de la nuit commencé, on garde la page faite avant.
    if args.html and slate.started and not args.force:
        from web_report import archive_path
        if archive_path(Path(args.html), slate).exists():
            print(f"{len(slate.started)} match(s) de la nuit déjà commencé(s) : "
                  "l'analyse d'avant le coup d'envoi est conservée (--force pour regénérer).")
            return 0

    if not slate.matchups:
        print("Aucun match NBA au calendrier pour cette date.")
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
    from web_report import write_site
    index = write_site(slate, evaluations, Path(out_dir))
    print(f"Page web générée : {index}")


if __name__ == "__main__":
    sys.exit(main())

# EU Tax Developments bot — cloud edition ☁️🇪🇺

Telegram-bot die Europese tax developments volgt (CIT- en BTW-tarieven, EU-richtlijnen)
met nadruk op NL, LU, DK, FI, NO, SE — en meldt wanneer iets **echt enacted** is.
Draait volledig op **GitHub Actions** (gratis), dus ook als je laptop uit staat.

## 👉 Installeren: zie [SETUP_CLOUD.md](SETUP_CLOUD.md)

## Onderdelen

| Bestand | Rol |
|---------|-----|
| `tax_monitor.py` | Dagelijkse nieuws-scan → alerts (🔴 ENACTED / 🟡 PROPOSAL / 🔵 UPDATE) |
| `overview.py` | Volledig CIT + EU overzicht |
| `poller.py` | Verwerkt Telegram-commando's (`/overview`, `/cit`, `/eu`, `/scan`, `/help`) |
| `sources.py` | Nieuwsbronnen (Google News-queries + Tax Foundation) |
| `classifier.py` | Relevantie + ENACTED/PROPOSAL-classificatie (meertalig) |
| `settings.py` | Laadt geheimen uit env-variabelen (config.json als fallback) |
| `cit_baseline.json` | CIT-tarieven per land (bron: Tax Foundation 2026) |
| `state.json` | Dedup-geheugen (wordt door de workflow teruggecommit) |
| `config.json` | Instellingen **zonder geheimen** |
| `.github/workflows/` | `alerts.yml`, `overview.yml`, `poll.yml` |

## Geheimen

Worden **nooit** in de repo gezet. GitHub Actions injecteert ze als env-variabelen
uit repository **Secrets**:

- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`

## Lokaal draaien (optioneel, voor test)

```powershell
$env:TELEGRAM_TOKEN = "..."; $env:TELEGRAM_CHAT_ID = "..."
pip install -r requirements.txt
python overview.py      # stuurt het overzicht
python tax_monitor.py   # draait een scan
```

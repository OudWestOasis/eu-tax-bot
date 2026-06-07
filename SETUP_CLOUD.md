# ☁️ Cloud-setup — EU Tax Developments bot op GitHub Actions

Deze map is een **zelfstandige repo** die de bot volledig in de cloud draait,
gratis, ook als je laptop uit of dicht is. Geen 24/7-server: alles draait op
geplande GitHub Actions-workflows.

## Wat zit erin

| Workflow | Wat | Schema (UTC) | = Amsterdam |
|----------|-----|--------------|-------------|
| `alerts.yml` | Dagelijkse nieuws-scan → nieuwe ontwikkelingen | `0 6 * * *` | 07:00 (winter) / 08:00 (zomer) |
| `overview.yml` | Wekelijks volledig CIT + EU overzicht | `30 6 * * 1` (ma) | 07:30 / 08:30 |
| `poll.yml` | Commando's ophalen & beantwoorden | `*/5 * * * *` | elke 5 min |

> **Cron is altijd UTC en kent géén zomertijd.** Daarom verschuift de lokale tijd
> een uur tussen winter en zomer. Wil je exact 07:00 het hele jaar? Pas de cron
> 2× per jaar aan (winter `0 6`, zomer `0 5`).

---

## Stap A — Repo aanmaken & pushen

De map is al een git-repo met een eerste commit. Je hoeft alleen een lege repo op
GitHub te maken en te pushen.

**Optie 1 — via de GitHub website:**
1. Ga naar <https://github.com/new>
2. Repository name: bv. `eu-tax-bot` · zet op **Public** (nodig voor onbeperkte gratis Actions-minuten bij 5-min-polling) · **géén** README/.gitignore aanvinken
3. Klik **Create repository**
4. Koppel en push (vervang `JOUW-NAAM`):
   ```powershell
   cd "C:\Users\joris\Claude\Tax (AI) Control Framework\eu-tax-bot-cloud"
   git remote add origin https://github.com/JOUW-NAAM/eu-tax-bot.git
   git branch -M main
   git push -u origin main
   ```

**Optie 2 — via GitHub CLI (`gh`), in één commando:**
```powershell
cd "C:\Users\joris\Claude\Tax (AI) Control Framework\eu-tax-bot-cloud"
gh repo create eu-tax-bot --public --source=. --remote=origin --push
```

---

## Stap B — Secrets instellen (EXACTE namen)

In je repo op GitHub: **Settings → Secrets and variables → Actions →
New repository secret**. Maak deze twee aan:

| Secret-naam | Waarde |
|-------------|--------|
| `TELEGRAM_TOKEN` | Je bot-token van BotFather (staat in je lokale `eu_tax_monitor\config.json`) |
| `TELEGRAM_CHAT_ID` | Je chat-id (staat in diezelfde lokale `config.json`, veld `chat_id`) |

> Plak deze waardes **alleen** in het GitHub Secrets-scherm — nooit in code of in
> een commit. De repo bevat bewust een lege `config.json`.

---

## Stap C — Lokale versie uitzetten ⚠️ (BELANGRIJK, vóór je gaat testen)

De lokale listener én de cloud-poller praten allebei met Telegram via
`getUpdates`. **Twee tegelijk botsen** (Telegram-fout 409). Zet daarom de lokale
versie uit zodra de cloud klaarstaat:

```powershell
# stop de meeluisterende bot
Stop-Process -Name pythonw -Force -ErrorAction SilentlyContinue

# verwijder de automatische start bij inloggen
Remove-Item "$([Environment]::GetFolderPath('Startup'))\EU Tax Bot Listener.vbs" -ErrorAction SilentlyContinue

# zet de geplande taken uit
Disable-ScheduledTask -TaskName "EU Tax Developments Bot"
Disable-ScheduledTask -TaskName "EU Tax Overview Weekly"
```
(Of draai `disable_local.ps1` in de map `eu_tax_monitor`.)

---

## Stap D — Elke workflow testen

Ga naar het tabblad **Actions** in je repo. Per workflow:
1. Kies de workflow links (bv. *Daily tax alerts*).
2. Klik rechts **Run workflow** → **Run workflow** (dat is de `workflow_dispatch`-testknop).
3. Open de run en bekijk de logs.

| Workflow | Verwacht resultaat |
|----------|--------------------|
| **Daily tax alerts** | Run groen; in Telegram nieuwe items (of "No new items" in de log als er niets nieuws is). `state.json` wordt teruggecommit als er iets veranderde. |
| **Weekly overview** | Run groen; je krijgt het volledige CIT + EU overzicht in Telegram. |
| **Poll commands** | Typ eerst `/overview` in Telegram, start dan deze workflow. Run groen; je krijgt antwoord. (Zonder openstaand bericht: log zegt "No pending messages".) |

---

## Aandachtspunten

- **Cron-vertraging:** geplande Actions starten vaak **enkele minuten te laat**
  (soms 10–30 min) bij drukte op GitHub. Niet stipt, wel betrouwbaar genoeg.
- **Gratis minuten:** deze repo is **Public**, dus Actions-minuten zijn
  **onbeperkt en gratis** — daarom kan de poll op elke 5 min. (Op een privé-repo
  zou `*/5` ~8640 runs/maand zijn, ver boven de 2000 gratis minuten.) Let op:
  bij een public repo is de **code zichtbaar** voor iedereen — maar je geheimen
  niet: die staan als GitHub Secrets, nooit in de code.
- **60-dagen-pauze:** GitHub zet `schedule`-workflows **automatisch uit na 60
  dagen zonder repo-activiteit**. De `state.json`-commits van de alerts-workflow
  houden de repo actief, dus dit speelt normaal niet — maar als alles 2 maanden
  stil ligt, open de repo en druk één keer **Run workflow** om ze te heractiveren.
- **Eén getUpdates-consumer:** draai nooit de lokale listener én de cloud-poll
  tegelijk (zie stap C).
- **State in git:** `state.json` (dedup-geheugen) wordt door de workflow
  teruggecommit, omdat cloud-runners wegwerpbaar zijn. Je ziet dus automatische
  commits "Update dedup state" — dat hoort zo.
- **CIT-data bijwerken:** `cit_baseline.json` aanpassen → commit & push; de
  volgende run gebruikt de nieuwe cijfers.

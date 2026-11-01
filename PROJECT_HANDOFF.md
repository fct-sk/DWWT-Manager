# DWWT Manager — Project handoff

Stav k **1. novembru 2026**. Tento dokument sumarizuje stav projektu po samostatnom OPTION B a Household v6 commite.

## Rýchly stav

- Repository: `fct-sk/DWWT-Manager`, branch `main`.
- Posledný stabilný referenčný checkpoint: OPTION B commit `efcc764` — explicitný blower switch entity.
- Household v6 commit: `de717d8` — `feat: add household load profile`.
- Household v6 je samostatne commitnutá a testovaná.
- Pracovný strom obsahuje iba necommitnutú zmenu `custom_components/dwwt_manager/manifest.json` na `0.1.0-beta.7`.
- Household v6 a OPTION B neboli pushnuté v tejto práci. Skontrolujte `git status -sb` pred ďalšími úkonmi.
- Žiadny MQTT Controller kód nie je implementovaný.

## Commity a hranice verzií

| Oblasť | Verzia | Referencia |
|---|---:|---|
| OPTION B: explicitný HA blower switch | ConfigEntry v5 | `efcc764` |
| Household Load Profile | ConfigEntry v6 | `de717d8` |
| Vydanie integrácie | manifest Beta7 | Zatiaľ iba working-tree zmena |
| Budúca MQTT Controller vrstva | plánovaná v7 | Neimplementovaná |

ConfigEntry verzia, `HouseholdLoadProfile.schema_version` a verzia release v `manifest.json` sú samostatné číslovania.

## OPTION B — hotové

Blower sa vyberá ako konkrétna Home Assistant `switch` entita. Je to jediný autoritatívny control target. Jej registry UUID zachováva identitu pri premenovaní; odstránená entita sa nikdy automaticky nenahrádza iným výstupom. Vlastnícke HA zariadenie je iba odvodený kontext.

Migrácia starej device konfigurácie zvolí switch automaticky len vtedy, keď zariadenie obsahuje presne jeden platný switch. Pri nule alebo viacerých switchoch je potrebná rekonfigurácia. Pumpové device/sensor správanie zostalo oddelené.

`MeasurementBinding` je samostatný pasívny kontrakt. Predvolený rozsah je `unknown`; vlastník zariadenia sa nezamieňa s fyzickým rozsahom merania. Automatické blower energy monitoring sa nepridalo.

## Household v6 — hotové

`household_profile` je samostatný objekt:

```json
{
  "schema_version": 1,
  "typical_occupants": null,
  "occupancy_pattern": "unknown",
  "peak_occupants": null
}
```

Počty sú nezáporné celé hodnoty; `null` znamená neznáme a nula je skutočná nula. Známý peak nesmie byť nižší než typical. Počet nie je limitovaný `nominal_eo`. Profil nemení režim, AUTO rozhodovanie ani aeráciu.

Config flow a options ukladajú celý profil ako jeden objekt. Peak je voliteľný. SK/EN texty, vysvetlivky, enumy a validácie sú zahrnuté.

ConfigEntry migrácia najprv vykoná staré migrácie a OPTION B prevod do v5, potom household migráciu do v6:

- Existujúci validný profil má prednosť pred legacy `occupants`.
- Ak sú profily v `data` aj `options`, zachová sa options profil ako celok; polia sa nemiešajú.
- Bez existujúceho profilu sa použije legacy `occupants` s precedence options → data.
- Kladný počet sa prevedie; legacy 0 alebo missing sa prevedie na `null`.
- Pattern bude `unknown`, peak `null`.
- Legacy `occupants` sa odstráni po úspešnom vytvorení výslednej konfigurácie.
- `estimated_eo` a `load_factor` sa zachovajú presne v pôvodnom kontajneri; nie sú súčasťou HouseholdLoadProfile.
- Pri neplatnom profile migrácia neuloží čiastočný výsledok a nezvýši ConfigEntry verziu.

`load_contracts.py` obsahuje iba pasívne dátové typy. `ActualLoadEstimate` je rezervovaný tvar kontraktu; nie je estimator a nič ho nevypočítava. Alarmová sémantika je pevne zdokumentovaná: `armed_night` znamená obsadený nočný režim, `armed_away` neprítomnosť. Chýbajúce dáta neznamenajú nulovú aktivitu.

## Aeration a AUTO — zachovať

Beta6 V1 matematika a AUTO správanie zostávajú bez zmien. `nominal_eo` je nominálna/projektová kapacita ČOV, nie aktuálny počet obyvateľov ani aktuálne zaťaženie. Household profil nevstupuje do výpočtu.

Známe referencie pre 3 m³ a 60 L/min: 6 nominal EO NORMAL 240/240, LOW_LOAD 80/400, HEAVY_LOAD 300/180, ECO 10/470; 2 nominal EO NORMAL 80/400. Horný ON limit 420 minút je technický/heuristický limit, nie technologicky potvrdená hranica.

## MQTT Controller — ďalšia etapa, ešte nezačatá

Schválený dokument **DWWT Manager ↔ Controller MQTT Protocol — V1 (Approved)** je jediný source of truth. V konverzácii bol odovzdaný súbor `DWWT Manager–Controller MQTT Protocol V1 (Approved).md`; dokument sa podľa doterajšej kontroly nachádza mimo repository. Pred implementáciou ho treba znova sprístupniť alebo pridať do projektu, ak ho nový pracovný kontext nevie prečítať.

Potvrdené protokolové body:

- Manager vlastní mode, AUTO, aeration schedule, desired state a PersistentState.
- Controller vlastní fyzický výstup a lokálny fail-safe.
- `controller_id` je stabilná hardvérová identita, ručne párovaná, nezávislá od HA `entry_id`.
- Sekvencia je persistentná revízia desired state; zvyšuje sa iba pri zmene ON/OFF. Heartbeat používa aktuálnu sekvenciu.
- Heartbeat 30 s; Controller timeout 120 s.
- `RETAIN=0` je delivery-based liveness; retain flag a sequence majú odlišné úlohy.
- Pri Controller offline Manager zmrazí zostávajúci čas fázy; pri návrate obnoví fázu a publikuje aktuálny cieľ.
- Recovery Reconciliation sa riadi presne §7.3 a §10.7 protokolu.
- `actual_state` a `fail_safe_active` sú diagnostické; nikdy neovplyvňujú Manager plánovanie/fázu.
- Fail-safe konfigurácia má samostatnú sekvenciu, default 240/240 min a schválenú validáciu celých minút 1–1440.
- `control_enabled` má byť persistentné; heartbeat pokračuje aj pri vypnutom plánovaní.
- Direct HA OPTION B cesta musí zostať funkčná.

Nekopírujte Controller pravidlá zo starších auditov, ak odporujú schválenému dokumentu. MQTT implementácia bola odložená do budúcej ConfigEntry v7, po household v6.

## Overenie Household v6

- Working tree aj samostatný export presného staged snapshotu prešli **113 testami**; jeden warning pochádza z Home Assistant aiohttp deprecation.
- Syntax/compileall, JSON validácia, EN source parity, cielený Ruff a `git diff --cached --check` prešli.
- Kompletný repository Ruff nebol čistý: posledná kontrola hlásila 94 existujúcich nálezov prevažne v nezmenenom/import-star kóde.
- UI nebolo manuálne vyskúšané v bežiacej HA inštancii.

Znovu spustiť testy po ďalšej zmene:

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m compileall -q custom_components tests
.venv/Scripts/python.exe -m ruff check .
```

## Odporúčaný ďalší postup

1. Skontrolovať stav `main` a či sú commity `efcc764` a `de717d8` už na `origin/main`.
2. Rozhodnúť, či je samostatná Beta7 manifest zmena pripravená na commit/release; momentálne je unstaged.
3. Ak sa začne MQTT implementácia, pracovať od Household v6 checkpointu, znovu načítať schválený Protocol V1 celý a rozdeľovať MQTT do samostatného v7 kroku.
4. Pred MQTT kódom navrhnúť/migrovať PersistentState sequence, `control_enabled`, perzistentný fail-safe config sequence a controller-bound identitu podľa protokolu.
5. Nepridávať estimator, nové AUTO rozhodovanie, aeration zmeny, ESP32 firmware ani Controller runtime do Manager v tejto fáze.

## Kde hľadať

- `custom_components/dwwt_manager/household.py` — HouseholdLoadProfile a ConfigEntry migrácia.
- `custom_components/dwwt_manager/load_contracts.py` — pasívne budúce pozorovacie kontrakty.
- `custom_components/dwwt_manager/config_flow.py` — setup/options a verzie ConfigEntry.
- `custom_components/dwwt_manager/__init__.py` — setup a ConfigEntry migrácie.
- `custom_components/dwwt_manager/aeration.py`, `models.py`, `manager.py` — aktuálna aeration/AUTO/runtime logika.
- `custom_components/dwwt_manager/device_resolver.py` — OPTION B blower resolver a pumpové resolvery.
- `custom_components/dwwt_manager/measurements.py` — MeasurementBinding.
- `tests/test_household.py`, `tests/test_blower_control.py`, `tests/test_aeration.py`, `tests/test_models.py` — hlavné testy.

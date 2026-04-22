# Hidroelectrica România — Integrare Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/sarbuandreidaniel/hidroelectrica?style=flat-square&label=Versiune)](https://github.com/sarbuandreidaniel/hidroelectrica/releases)
[![HA Min Version](https://img.shields.io/badge/Home%20Assistant-%3E%3D2024.1.0-blue?style=flat-square)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/Licen%C8%9B%C4%83-MIT-green.svg?style=flat-square)](LICENSE)
[![Susține](https://img.shields.io/badge/Sus%C8%9Bine-Buy%20Me%20a%20Coffee-yellow?style=flat-square&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/sarbuandreidaniel)
[![Revolut](https://img.shields.io/badge/Sus%C8%9Bine--m%C4%83%20prin-Revolut-blue?style=flat-square&logo=revolut)](https://revolut.me/andreisarbu/pocket/BPJpX9dppQ)

O integrare profesională pentru Home Assistant care conectează contul tău **Hidroelectrica România** direct la platforma de smart home. Monitorizează consumul de energie electrică, soldul contului, facturile, indexul contorului și mult mai mult — totul dintr-un singur loc.

---

## Ce oferă integrarea

### Funcționalități disponibile
- **Autentificare securizată** — Login prin portalul iHidro, același mecanism ca aplicația oficială
- **Mai multe contracte** — Suport complet pentru conturi cu mai multe locuri de consum; fiecare contract apare ca un dispozitiv separat în HA
- **Sold cont** — Soldul în timp real, exprimat în RON
- **Index contor** — Index energie consumată, produsă (fotovoltaic) și estimat curent
- **Transmitere index** — Buton dedicat per contract pentru trimiterea indexului citit; valorile se introduc prin entitățile `number` și se trimit cu un singur apăsat
- **Facturi** — Scadențe, sume, numere de factură și stare restanțe
- **Consum** — Consum și cost pentru luna anterioară, medie lunară și vârf anual
- **Istoric facturare** — Istoricul complet pentru anul curent și cel precedent, separat pe energie consumată și produsă
- **Date contor** — Serie contor, cod POD, data ultimei citiri

### În curând
- 📋 Grafice și statistici de consum
- 📋 Alerte de plată prin notificări HA

---

## Instalare

### Prin HACS (Recomandat)

1. Asigură-te că [HACS](https://hacs.xyz/) este instalat
2. Mergi la **HACS → Integrări → ⋮ → Depozite personalizate**
3. Adaugă:
   - **URL:** `https://github.com/sarbuandreidaniel/hidroelectrica`
   - **Categorie:** Integration
4. Caută **Hidroelectrica** și instalează
5. Repornești Home Assistant

### Instalare manuală

```bash
cp -r custom_components/hidroelectrica ~/.homeassistant/custom_components/
```

Apoi repornești Home Assistant.

---

## Configurare

1. Mergi la **Setări → Dispozitive și servicii → Integrări**
2. Apasă **Adaugă integrare** și caută **Hidroelectrica**
3. Introdu datele de autentificare ale portalului iHidro:
   - **Utilizator sau Email** — username-ul sau adresa de email înregistrată la Hidroelectrica
   - **Parolă** — parola contului tău
4. Apasă **Trimite**

Integrarea se va autentifica, va prelua datele contorului tău și va crea automat toți senzorii.

---

## Senzori disponibili

| Senzor | Descriere | Unitate |
|--------|-----------|---------|
| `sensor.hidroelectrica_<pod>_balance` | Soldul curent al contului | RON |
| `sensor.hidroelectrica_<pod>_unpaid_invoice` | Suma facturii neachitate | RON |
| `sensor.hidroelectrica_<pod>_meter_consumed` | Index energie activă consumată | kWh |
| `sensor.hidroelectrica_<pod>_meter_produced` | Index energie activă produsă (fotovoltaic) | kWh |
| `sensor.hidroelectrica_<pod>_meter_estimated` | Index estimat curent | kWh |
| `sensor.hidroelectrica_<pod>_last_reading_date` | Data ultimei citiri a contorului | — |
| `sensor.hidroelectrica_<pod>_meter_serial` | Seria contorului | — |
| `sensor.hidroelectrica_<pod>_pod` | Codul POD al locului de consum | — |
| `sensor.hidroelectrica_<pod>_last_month_kwh` | Consum luna anterioară | kWh |
| `sensor.hidroelectrica_<pod>_consumption_history_AAAA` | Consum total energie în anul AAAA | kWh |
| `sensor.hidroelectrica_<pod>_invoice_history_consumed_AAAA` | Total facturat energie consumată în AAAA | RON |
| `sensor.hidroelectrica_<pod>_invoice_history_produced_AAAA` | Total facturat energie produsă în AAAA | RON |

> `<pod>` este derivat automat din codul POD sau seria contorului. Senzorii de istoric sunt generați automat pentru **anul curent** și **anul precedent**.

### Atribute senzori

**`sensor.hidroelectrica_<uan>_unpaid_invoice`** include:
- `due_date` — Data scadenței facturii neachitate
- `days_until_due` — Zile rămase până la scadență
- `overdue` — `true` dacă scadența a trecut

**`sensor.hidroelectrica_<uan>_consumption_history_AAAA`** include:
- Consum lunar (kWh) pentru fiecare lună disponibilă
- `total_kwh`, `average_monthly_kwh`, `average_daily_kwh`

**`sensor.hidroelectrica_<uan>_invoice_history_consumed_AAAA`** și **`sensor.hidroelectrica_<uan>_invoice_history_produced_AAAA`** includ:
- `Invoice 1 DD/MM/YYYY` … `Invoice N DD/MM/YYYY` — suma fiecărei facturi în RON
- `total_invoices` — numărul total de facturi din an
- `total_amount_paid` — suma totală plătită în an (RON)
- `average_monthly_amount` — media lunară (RON)
- `average_daily_amount` — media zilnică (RON)

---

## Automatizări și șabloane

Exemplu — alertă când apare o factură restantă:

```yaml
automation:
  - alias: "Factură Hidroelectrica restantă"
    trigger:
      - platform: template
        value_template: "{{ state_attr('sensor.hidroelectrica_8000123456_unpaid_invoice', 'overdue') == true }}"
    action:
      - service: notify.mobile_app
        data:
          title: "Factură Hidroelectrica"
          message: "Ai o factură restantă de {{ states('sensor.hidroelectrica_8000123456_unpaid_invoice') }} RON"
```

Exemplu — trimitere automată a indexului în prima zi a lunii:

```yaml
automation:
  - alias: "Trimite index Hidroelectrica"
    trigger:
      - platform: time
        at: "08:00:00"
    condition:
      - condition: template
        value_template: "{{ now().day == 1 }}"
    action:
      - service: button.press
        target:
          entity_id: button.hidroelectrica_8000123456_submit_meter
```

Exemplu — trimitere automată a indexului în prima zi a lunii:

```yaml
automation:
  - alias: "Trimite index Hidroelectrica"
    trigger:
      - platform: time
        at: "08:00:00"
    condition:
      - condition: template
        value_template: "{{ now().day == 1 }}"
    action:
      - service: button.press
        target:
          entity_id: button.hidroelectrica_8000123456_submit_meter
```

---

## Rezolvarea problemelor

| Problemă | Soluție |
|----------|---------|
| Date de autentificare invalide | Folosește username-ul (nu email-ul) și parola contului iHidro |
| Fără date / senzori indisponibili | Verifică jurnalele HA și conexiunea la internet |
| Date vechi | Intervalul implicit de actualizare este 5 minute; repornește integrarea pentru o actualizare forțată |
| Index energie produsă mereu 0 | Normal dacă nu ai instalație fotovoltaică înregistrată |

### Script de depanare

Testează autentificarea și toate endpoint-urile independent de Home Assistant:

```bash
cd /path/to/ha-hidroelectrica
pip install aiohttp python-dotenv
python3 scripts/test.py
```

Sau cu credențiale din variabile de mediu:

```bash
HIDRO_USERNAME=userul_tau HIDRO_PASSWORD=parola_ta python3 scripts/test.py
```

---

## Confidențialitate și securitate

- Datele de autentificare sunt stocate securizat prin sistemul de intrări de configurare al Home Assistant — niciodată în text simplu
- Se fac doar apelurile API strict necesare către portalul iHidro
- Nicio dată nu este trimisă către servicii terțe
- Conform GDPR — toate datele rămân local în instanța ta Home Assistant

---

## Dezvoltare

### Structura proiectului

```
ha-hidroelectrica/
├── custom_components/hidroelectrica/
│   ├── __init__.py           # Configurare integrare și coordinator
│   ├── api.py                # Client API iHidro
│   ├── auth.py               # Autentificare portal
│   ├── config_flow.py        # Flux de configurare UI
│   ├── const.py              # Constante
│   ├── coordinator.py        # DataUpdateCoordinator
│   ├── sensor.py             # Entități senzori
│   ├── manifest.json         # Metadate integrare
│   └── translations/
│       ├── en.json           # Traduceri engleze
│       └── ro.json           # Traduceri române
└── scripts/
    └── test.py               # Script de depanare (testare în afara HA)
```

### Contribuții

Pull request-urile sunt binevenite. Te rugăm să deschizi un issue înainte de modificări majore.

---

## Susține proiectul

Dacă această integrare îți economisește timp și îți face casa mai inteligentă, poți susține dezvoltarea ei:

[![Susține cu o cafea](https://img.shields.io/badge/Cump%C4%83r%C4%83--mi%20o%20cafea-Sus%C8%9Bine%20proiectul-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/sarbuandreidaniel)

[![Susține-mă prin Revolut](https://img.shields.io/badge/Sus%C8%9Bine--m%C4%83%20prin-Revolut-blue?style=for-the-badge&logo=revolut)](https://revolut.me/andreisarbu/pocket/BPJpX9dppQ)

---

## Licență

Licențiat sub [MIT License](LICENSE).

---

> **Disclaimer:** Aceasta este o integrare neoficială, dezvoltată de comunitate. Nu este afiliată cu și nu este aprobată de Hidroelectrica S.A. Folosești pe propria răspundere și respectând termenii și condițiile Hidroelectrica.

---

**Autor:** [Andrei Sarbu](https://github.com/sarbuandreidaniel) · **Versiune:** 0.3.0 · **Actualizat:** Aprilie 2026

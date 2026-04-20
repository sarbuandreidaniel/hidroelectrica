# Hidroelectrica România — Integrare Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub Release](https://img.shields.io/github/v/release/sarbuandreidaniel/ha-hidroelectrica?style=flat-square&label=Versiune)](https://github.com/sarbuandreidaniel/ha-hidroelectrica/releases)
[![HA Min Version](https://img.shields.io/badge/Home%20Assistant-%3E%3D2024.1.0-blue?style=flat-square)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/Licen%C8%9B%C4%83-MIT-green.svg?style=flat-square)](LICENSE)
[![Susține](https://img.shields.io/badge/Sus%C8%9Bine-Buy%20Me%20a%20Coffee-yellow?style=flat-square&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/sarbuandreidaniel)
[![Revolut](https://img.shields.io/badge/Sus%C8%9Bine--m%C4%83%20prin-Revolut-blue?style=flat-square&logo=revolut)](https://revolut.me/andreisarbu/pocket/BPJpX9dppQ)

O integrare profesională pentru Home Assistant care conectează contul tău **Hidroelectrica România** direct la platforma de smart home. Monitorizează consumul de energie electrică, soldul contului, facturile, indexul contorului și mult mai mult — totul dintr-un singur loc.

---

## Ce oferă integrarea

### Funcționalități disponibile
- **Autentificare securizată** — Login prin portalul iHidro, același mecanism ca aplicația oficială
- **Sold cont** — Soldul în timp real, exprimat în RON
- **Index contor** — Index energie consumată, produsă (fotovoltaic) și estimat curent
- **Facturi** — Scadențe, sume, numere de factură și stare restanțe
- **Consum** — Consum și cost pentru luna anterioară, medie lunară și vârf anual
- **Istoric facturare** — Istoricul complet pentru anul curent și cel precedent, separat pe energie consumată și produsă
- **Date contor** — Serie contor, cod POD, data ultimei citiri

### În curând
- 📋 Transmitere automată a indexului
- 📋 Grafice și statistici de consum
- 📋 Suport pentru mai multe locuri de consum
- 📋 Alerte de plată prin notificări HA

---

## Instalare

### Prin HACS (Recomandat)

1. Asigură-te că [HACS](https://hacs.xyz/) este instalat
2. Mergi la **HACS → Integrări → ⋮ → Depozite personalizate**
3. Adaugă:
   - **URL:** `https://github.com/sarbuandreidaniel/ha-hidroelectrica`
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
| `sensor.hidroelectrica_sold_curent` | Soldul curent al contului | RON |
| `sensor.hidroelectrica_data_scadenta` | Data scadenței facturii curente | — |
| `sensor.hidroelectrica_zile_pana_la_scadenta` | Zile rămase până la scadență | zile |
| `sensor.hidroelectrica_suma_factura_neachitata` | Suma facturii neachitate | RON |
| `sensor.hidroelectrica_scadenta_factura` | Data scadenței facturii neachitate | — |
| `sensor.hidroelectrica_numar_factura` | Numărul facturii neachitate | — |
| `sensor.hidroelectrica_factura_restanta` | Factură restantă da/nu | — |
| `sensor.hidroelectrica_index_energie_activa_consumata` | Index energie activă consumată | kWh |
| `sensor.hidroelectrica_index_energie_activa_produsa` | Index energie activă produsă (fotovoltaic) | kWh |
| `sensor.hidroelectrica_index_estimat_curent` | Index estimat curent | kWh |
| `sensor.hidroelectrica_data_ultimei_citiri` | Data ultimei citiri a contorului | — |
| `sensor.hidroelectrica_serie_contor` | Seria contorului | — |
| `sensor.hidroelectrica_pod` | Codul POD al locului de consum | — |
| `sensor.hidroelectrica_consum_luna_anterioara` | Consum luna anterioară | kWh |
| `sensor.hidroelectrica_cost_luna_anterioara` | Cost luna anterioară | RON |
| `sensor.hidroelectrica_cost_mediu_lunar` | Costul mediu lunar | RON |
| `sensor.hidroelectrica_varf_consum_anual` | Vârful de consum din ultimul an | RON |
| `sensor.hidroelectrica_istoricul_facturarii_AAAA` | Istoricul facturării pentru anul AAAA | — |
| `sensor.hidroelectrica_istoricul_energiei_produse_AAAA` | Istoricul facturilor energie produsă pentru AAAA | — |

> Senzorii de istoric sunt generați automat pentru **anul curent** și **anul precedent**.

### Atribute senzori de istoric

**`sensor.hidroelectrica_istoricul_facturarii_AAAA`** și **`sensor.hidroelectrica_istoricul_energiei_produse_AAAA`** includ:
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
      - platform: state
        entity_id: sensor.hidroelectrica_factura_restanta
        to: "true"
    action:
      - service: notify.mobile_app
        data:
          title: "Factură Hidroelectrica"
          message: "Ai o factură restantă de {{ states('sensor.hidroelectrica_suma_factura_neachitata') }} RON"
```

---

## Rezolvarea problemelor

| Problemă | Soluție |
|----------|---------|
| Date de autentificare invalide | Folosește username-ul (nu email-ul) și parola contului iHidro |
| Fără date / senzori indisponibili | Verifică jurnalele HA și conexiunea la internet |
| Date vechi | Intervalul implicit de actualizare este 5 minute; repornește integrarea pentru o actualizare forțată |
| Index energie produsă mereu 0 | Normal dacă nu ai instalație fotovoltaică înregistrată |

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
custom_components/hidroelectrica/
├── __init__.py           # Configurare integrare și coordinator
├── api.py                # Client API iHidro
├── auth.py               # Autentificare portal
├── config_flow.py        # Flux de configurare UI
├── const.py              # Constante
├── coordinator.py        # DataUpdateCoordinator
├── sensor.py             # Entități senzori
├── manifest.json         # Metadate integrare
└── translations/
    ├── en.json           # Traduceri engleze
    └── ro.json           # Traduceri române
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

**Autor:** [Andrei Sarbu](https://github.com/sarbuandreidaniel) · **Actualizat:** Aprilie 2026

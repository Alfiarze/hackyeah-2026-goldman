# AI Control Layer — Goldman Sachs

> **HackYeah 2026 · Zadanie partnerskie · sponsor: Proidea / partner merytoryczny: Goldman Sachs**
> Nagrody: **15 000 zł** (I — 6 000, II — 5 000, III — 4 000) · Zgłoszenie: **polski lub angielski**
> ✅ Autorskie prawa majątkowe **NIE przechodzą** na sponsora

---

## 1. Kontekst — problem biznesowy

Organizacje coraz szerzej wdrażają AI i **Agentic AI** (agenci piszą kod, tworzą dokumenty, analizują dane, automatyzują procesy). To skok produktywności, ale też **nowa klasa ryzyk, na które tradycyjne narzędzia bezpieczeństwa nie są gotowe**:

### Zagrożenia ery agentów
| Ryzyko | Na czym polega |
|---|---|
| **Dynamiczne uprawnienia** | Systemy agentowe wymagają nowoczesnego uwierzytelniania i kontroli dostępu. Bez lokalnego egzekwowania agent sięga po zasoby, do których nie powinien mieć dostępu, **podszywa się pod innych aktorów** i wykonuje szkodliwe, nieodwracalne akcje |
| **Prompt injection** | W przeciwieństwie do aplikacji ze strukturyzowanym inputem, AI interpretuje język naturalny jako logikę wykonania — bez walidacji wejścia i filtra wyjścia **zwraca wrażliwe dane** |
| **Pamięć i zasoby** | Agenci z trwałym kontekstem / współdzieloną pamięcią mogą wywoływać nieautoryzowane pobieranie danych lub wpadać w **pętle runaway**; niedeterministyczne zachowanie = nieprzewidywalnie wysokie zużycie zasobów |

### Co potrzebują organizacje
Kompleksowych kontroli (**guardrails**) egzekwowanych przez **elastyczną, adaptacyjną warstwę kontrolną** — „inteligentnego pośrednika", który **w czasie rzeczywistym** inspekcjonuje, redaguje lub blokuje niebezpieczne interakcje: **hybrydowo**, łącząc tradycyjne wymuszanie polityk z egzekwowaniem wspieranym AI.

> Wymienione zagrożenia to tylko przykłady. Przy projektowaniu analizuj ekosystem AI głęboko (np. **OWASP**) i rozważ inne kontrolki potrzebne do kompletnego, produkcyjnego systemu obrony.

---

## 2. Treść zadania

**Zbuduj lekką, elastyczną AI Control Layer** — w formie **gatewaya, proxy, middleware'u lub wrappera SDK** — która przechwytuje i nadzoruje interakcje z systemami AI. Warstwa musi egzekwować kontrole bezpieczeństwa, prywatności i zasobów zdefiniowane w **centralnym źródle konfiguracji** (katalog kontroli), generować raportowanie dla security teamów i managementu, oraz działać hybrydowo.

### Wyzwania projektowe (wprost wymienione)
1. **Hybrydowa architektura obrony** — balans szybkość ↔ głębokie semantyczne rozumienie: kontrole **non-AI (deterministyczne)** + **AI-based (semantyczne)**
2. **Zarządzanie budżetem** — dla komercyjnych API **i** modeli lokalnych
3. **Detekcja znanych ataków** — sygnatury historycznych exploitów podawane z zewnętrznego systemu
4. **Wiarygodność** — obowiązkowy kompletny, zautomatyzowany suite testowy: przypadki **pozytywne (dozwolone)** i **negatywne (blokowane/redagowane)**

---

## 3. Oczekiwany rezultat (4 deliverables)

| # | Deliverable | Co zawiera |
|---|---|---|
| 1 | **AI Control Layer** | Działający gateway/proxy/middleware/SDK wrapper łatwy do integracji przez deweloperów (komunikacja: agent↔agent, app↔agent, agent↔MCP, agent↔model). Można zbudować własnego agenta lub użyć gotowego jako pokazu. **Wymagany prosty diagram architektury.** |
| 2 | **Sample Configuration** | Udokumentowany plik polityk: konfiguracja guardrails, różne poziomy surowości/przylegania (adherence %), reguły budżetowe |
| 3 | **Interactive Dashboard** | UI: lista kontroli, ogólna postawa bezpieczeństwa, zablokowane zagrożenia, metryki (zużycie zasobów / koszty) |
| 4 | **Executable Test Suite** | Gotowy do uruchomienia suite weryfikujący implementację kontroli, w tym limity budżetowe i mitigację exploitów |

---

## 4. Wymagania formalne (6 punktów)

### 1) Centralized Policy Engine
Jedno źródło konfiguracji (plik/system) zarządzające:
- kontrolami/guardrails
- progami wrażliwości (**Block vs Redact** albo adherence %)
- listą dozwolonych modeli LLM
- budżetami zasobowymi/finansowymi

### 2) Controls / Guardrails
- **Deterministyczne (non-AI):** pattern matching (wykrywanie **PII, sekretów**), sprawdzanie wymagań autoryzacji/dostępu itd.
- **Semantyczne (AI-based):** gdzie możliwe — użycie modeli AI do zabezpieczania interakcji z systemami AI

### 3) Budget & Resource Governance
Egzekwowanie limitów: dostęp do zasobów, czas computingu, **wydatki tokenów** na LLM-e.

### 4) Historical Attack Mitigation
Wykrywanie i blokowanie wzorców znanych exploitów na systemy AI: **malicious code execution, unsafe deserialization, supply-chain exploits na repozytoria modeli.**

### 5) Security Reporting & Auditing
- metryki real-time (zablokowane interakcje, zużycie budżetu) — dla managementu
- **eksportowalne logi audytowe** — dla security teamów do analizy zagrożeń, naruszeń polityk, użycia systemu
- forma: dedykowany dashboard „or otherwise"

### 6) Self-Testing Suite
Automatyczne testy pokrywające **przypadki pozytywne i negatywne** wszystkich kontroli.

---

## 5. Wymagania techniczne i ograniczenia zasobów

- **Stack w pełni dowolny** — od zera (Go, Rust, Python…) albo na istniejących open-source'ach (sprawdźcie licencje!)
- Agenci, LLM-y i aplikacje konsumujące waszą warstwę — można użyć gotowych (**nie podlegają ocenie**)
- 🚫 **Żadnych pre-packaged datasetów, propriertary API ani hardware'u** — celowo, dla pełnej swobody architektonicznej
- 🚫 **Żadnych subskrypcji płatnych usług** (OpenAI, Anthropic, Copilot…) — cały system musi działać na wasim setupie
- ✅ Oczekiwane: otwarte biblioteki + **modele lokalne (np. Ollama)** + własne prompty testowe

---

## 6. Jak wygląda walidacja (bardzo konkretne!)

Ocena opiera się głównie na **waszych deliverables i spontanicznych akcjach bez przygotowania**:

1. **Sędziowie uruchamiają wasz test suite** — musi pozwalać testować zaimplementowane kontrolki (pozytywne + negatywne)
2. **Interaktywne testy live** — sędziowie podają ad-hoc prompty i obserwują reakcję systemu w czasie rzeczywistym
3. **Modyfikacja konfiguracji na żywo** — zmiana reguł, **usuwanie kontroli, zmiana progów**: jak warstwa reaguje? Czy zmiany działają w czasie rzeczywistym?
4. **Telemetria wydajności** — powinniście móc ją produkować (może być użyta do oceny)
5. Przegląd całości: architektura, dashboardy, logowanie (dla managementu i security)

---

## 7. Kryteria oceny

| Kryterium | Waga |
|---|---|
| **Robustness of the Solution and Quality of Guardrails** | **30%** |
| **Architecture and Performance Efficiency** | 20% |
| **Security Reporting** | 20% |
| **Completeness of the Self-Testing Suite** | 20% |
| **Practical Implementability and Scalability** | 10% |

*(w pliku RULES: testy 20% i wdrożeniowość 10%; w CRITERIA: testy 15% i wdrożeniowość 15% — margines błędu dokumentów; bez względu na wariant: **guardrails + testy to razem 50% oceny**)*

Próg: **min. 50% punktów w fazie 1** (ocena na platformie przez komisję min. 3 mentorów); finał = live pitch przed Jury.

---

## 8. Nagrody i zasady

- **I — 6 000 zł · II — 5 000 zł · III — 4 000 zł** (brutto; wypłata w 90 dni od ogłoszenia wyników)
- Prace startowe: nie wcześniej niż 3.10 godz. 11:00; zgłoszenie do 4.10 godz. 11:00
- Zgłoszenie: tytuł, nazwa zespołu, lista członków (1–6), opis projektu, prezentacja PDF (max 10 slajdów) + opcjonalnie repo/demo/screenshots — platforma HackTribe, PL lub EN
- Zmiany po terminie = nieważne
- ✅ Prawa autorskie **zostają u autorów**
- Wykluczenie: pokrewieństwo z Jurorami lub pracownikami sponsora

---

## 9. Plan na 24 h (sugestia)

1. **H0–H2:** mapa kontroli z OWASP (LLM Top 10, Agentic AI) → wybór 4–6 guardrails: PII/sekrety (deterministyczne) + prompt injection (semantyczne) + budżet tokenów + sygnatury exploitów
2. **H2–H6:** rdzeń: proxy/gateway + policy engine (YAML/JSON: progi Block/Redact, dozwolone modele, budżety) + **hot-reload konfiguracji** (sędziowie to testują!)
3. **H6–H12:** kontrolki deterministyczne (regexy PII/sekrety, auth) + semantyczne (lokalny model przez Ollama klasyfikuje intencję/czułość)
4. **H12–H16:** budżety (licznik tokenów per user/agent, hard-stop), feed sygnatur ataków z pliku zewnętrznego
5. **H16–H20:** dashboard (metryki: zablokowane, redagowane, zużycie budżetu) + eksport logów audytowych
6. **H20–H23:** **test suite (pozytywne+negatywne per kontrolka)** — to 20% oceny i pierwsza rzecz, którą sędziowie uruchamiają; diagram architektury
7. **H23–H24:** README, przykładowa konfiguracja z różnymi poziomami surowości, prezentacja, submit

> **Rozdźwięknik oceny:** sędziowie aktywnie szukają dziur (ad-hoc prompty, wyłączanie kontroli). System, który **bezpiecznie degraduje się przy zmianie konfiguracji** i ma szczelny test suite, wygrywa z ładnym dashboardem bez pokrycia.

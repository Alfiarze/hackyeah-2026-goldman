# Aegis — Q&A cheat sheet: pytania jury + odpowiedzi pod wygranie

Zasada odpowiedzi: **konkret → dowód → liczba → zamknięcie w jednym zdaniu.** Nigdy nie bronić się — jeśli jury trafi w słabość, przyznać w pół zdania i pokazać, że to świadomy kompromis z roadmapą. Wszystkie liczby poniżej są z repo/submission — mówić tylko takie, które da się udowodnić na żywo (`make test-docker`, dashboard, `/metrics`).

---

## A. Architektura i pozycjonowanie („czym się różnicie")

### „Czym się różnicie od LiteLLM / NeMo Guardrails / Llama Guard?"
**„Oni klasyfikują treść. My egzekwujemy uprawnienia i przepływ danych.** Llama Guard powie, czy prompt 'wygląda' groźnie; Aegis wie, że ten agent nigdy nie miał prawa wysłać maila na ten adres — i blokuje przed wykonaniem, z licznikiem po stronie serwera pokazującym zero wywołań. Do tego budżet z atomową rezerwacją i audyt per decyzja. Zresztą nie rywalizujemy: NeMo Guardrails można wpiąć jako szósty etap pipeline'u — u nas jest miejsce na takie wtyczki."

### „To jest przecież WAF/DLP dla agentów — co nowego?"
**„WAF i DLP patrzą na treść, a agent zawodzi na kontekście.** Ten sam mail jest OK o 9:00 i jest wyciekiem o 9:05 — zależnie od tego, co agent przeczytał przed chwilą. Żadne narzędzie patrzące na tekst tego nie widzi, bo PESEL zakodowany w base64 albo przetłumaczony na angielski przechodzi przez każdy regex. Nasz taint jest przypisany do zadania, nie do tekstu — parafraza nic nie zmienia."

### „Dlaczego deterministyczne reguły, a nie sam model?"
**„Bo determinizm wygrywa czasem i przewidywalnością: 0,36 ms na sprawdzenie treści, 2,3 ms na pełną decyzję zablokowaną — to 2–3 rzędy wielkości szybciej niż guardrail ML (18–500 ms), bez round-tripa do API.** A przede wszystkim: wynik reguły jest taki sam dziś i jutro, dla nas i dla audytora. Model u nas tylko zaostrza — nigdy nie odblokowuje — więc jego błąd nie jest krytyczny."

### „Co jeśli model-strażnik da się oszukać?"
**„Nic się nie stanie — i mamy na to test.** Oślepiony detektor to scenariusz ③ w dashboardzie: wymuszamy pomyłkę AI, a taint i tak blokuje, bo decyzja należy do warstwy deterministycznej. AI dokłada podejrzliwość, nigdy nie otwiera drzwi. Fail-closed: timeout guarda to BLOCK."

---

## B. Bezpieczeństwo rozwiązania („a jak wy to obejdą?")

### „A jeśli prompt injection przyjdzie z danymi, których reguły nie znają?"
**„To pytanie o warstwy, nie o pojedynczy filtr.** Instrukcja musi przejść: sygnatury ataków, heurystyki (w tym base64, leetspeak, zero-width, wieloetapowe), ocenę AI — a nawet jeśli PRZEJDZIE, to musi jeszcze trafić na ujście dozwolone przez mandat i taint. Injection to ryzyko dla treści; egzekucja należy do nas. Demo: umowa mówi 'wyślij na evil.com', agent słucha — i dostaje MANDATE-RCPT w 0,7 ms, licznik poczty: 0."

### „Agent może wywołać narzędzie bezpośrednio, z pominięciem gatewaya?"
**„Nie, i to jest architektoniczne, nie konfiguracyjne.** Poświadczenia do narzędzi trzyma wyłącznie gateway — agent dostaje kontrolowane wejście. Próba ominięcia = 401. Można to pokazać na żywo: wyciągnijmy agentowi klucze z env — nie ma ich tam."

### „Podszyjesz się pod inny task / innego agenta?"
**„Mandat jest podpisany HMAC-em sekretem serwera i związany z principal z klucza API, nie z body żądania.** Weryfikacja w czasie stałym (compare_digest). Delegacja tworzy mandat-podzbiór: dziecko nigdy nie ma więcej uprawnień niż rodzic, głębokość max 3, poufność dziedziczona."

### „Zgłaszający może wprost wpisać sekret w prompt i zobaczyć go w logach?"
**„Nie — i zaprojektowaliśmy audit pod to.** W logach ląduje rule_id, klasa danych i zakres spanów, nigdy treść sekretu. Jest test, który tego pilnuje. Sekret zostaje zablokowany jako SECRET_DETECTED, a w audycie widać, ŻE wykryto sekret, bez jego ujawnienia."

### „Base64 / tłumaczenie / homoglify pokonują wasz DLP?"
**„Regex — tak. Nasz taint — nie.** Detektory dodatkowo deobfuskują: base64 jest dekodowany i skanowany, zero-width usuwane, leetspeak normalizowany, NFKC łapie homoglify. Ale kluczowa linia obrony to taint: po przeczytaniu poufnej umowy zadanie JEST poufne niezależnie od tego, jak agent przeformułuje treść. Przetłumacz PESEL na słowa — clearance ujścia nadal zamyka wysyłkę."

---

## C. Budżet i wydajność (liczby, które jury lubi)

### „30 równoległych agentów — co się dzieje?"
**„Zero overspendu, i to jest testowane.** Rezerwacja jest atomowa — conditional UPDATE w jednej transakcji Postgresa, sprawdzanie i rezerwacja to jedna operacja. 30 agentów rzuca się na wspólną pulę: część dostaje rezerwację, reszta odmowę PRZED wywołaniem modelu. Nie płacimy za to, czego nie zatwierdziliśmy. Test przechodzi także na 4 workerach."

### „Jaki koszt dodaje sama ochrona?"
**„0,36 ms p50 na sprawdzenia treści, 2,3 ms pełna decyzja blokująca.** Model-strażnik ma własny budżet (`guard`) — koszt ochrony jest policzalny i widoczny w dashboardzie, nie ukrywany. Semantic działa tylko na treści niezaufanej i jest cache'owany po hashu."

### „Skaluje się?"
**„Gateway jest bezstanowy — stan siedzi w Postgresie, polityka przeładowuje się przez NOTIFY na wszystkie instancje.** Pionowo: p50 w milisekundach zostawia zapas; poziomo: dokładamy instancje za proxy. Zmiana polityki działa od następnego żądania, bez redeployu."

---

## D. Operacyjność („co jak zepsujemy / co w produkcji")

### „Zepsułem YAML — co się stanie?"
**„Nic — i to jest feature.** Zepsuty plik zostaje odrzucony (422, `POLICY_REJECTED` w audycie), ostatnia dobra polityka dalej chroni. Każda decyzja ma `policy_version`, historia wersji ma diff i rollback jednym kliknięciem. Wyłączenie kontroli jest możliwe, ale głośne: czerwony kafelek `CONTROL_DISABLED` + event w audycie."

### „Co jeśli zablokujecie coś, co powinno przejść? (false positive)"
**„Taint jest celowo konserwatywny — wolimy fałszywy alarm niż wyciek, i mówimy to wprost w dokumentacji.** Ale FP sterujemy per profil (strict/balanced/permissive), per kontrola block vs redact, i rozdzielamy 'zapomniane hasło' (przechodzi) od 'moje hasło to kitten12' (nie przechodzi) — takie przypadki mamy w testach jako case'y FP."

### „Integracja = przepisanie agenta?"
**„Nie: zmiana `base_url`** — gateway jest OpenAI-compatible, agent nie widzi różnicy. Albo SDK (`mandate_sdk.govern`), albo proxy MCP. `make run` i działa; wdrożenie produkcyjne to Coolify + domeny, co pokazaliśmy na żywo."

### „Ile tego utrzymujecie po hackathonie? / co jest roadmapą?"
**„Uczciwe granice mamy opisane: taint konserwatywny, streaming buforowany przed wydaniem, sandbox bez sieci.** Roadmapa: Research Airlock (zapytania niskiej poufności w osobnym zadaniu), Redis na bardzo wysokie RPS, eksport SIEM, podpisane pakiety polityk. Nie udajemy, że to gotowy produkt enterprise — to działający, przetestowany fundament."

---

## E. Zadanie i kryteria („czy spełniacie wymagania")

### „Gdzie jest który wymóg zadania?"
**„Każdy wymóg ma moduł i parę testów: pozytywną i negatywną.** 10 etapów pipeline'u mapuje się 1:1 na kartę zadania: polityka centralna, kontrole deterministyczne, semantyczna, budżet, historyczne ataki (pickle, CVE-2024-34359, typosquat, MCP poisoning), raportowanie, self-testing. 334 testy jednym poleceniem: `make test-docker`. Tabelę mapowania pokazujemy na slajdzie 7."

### „Pokazcie, że to działa — teraz."
**„Trzy dowody, po 20 sekund każdy: (1) `make test-docker` — 334 testy; (2) scenariusz 'Poisoned contract' w dashboardzie — zablokowany mail, licznik usługi pocztowej: 0; (3) 'Launch 30 agents' — rezerwacje vs odmowy, zero tokenów ponad budżet.** Potem proszę o własny prompt w Live test — nie mamy nic do ukrycia, jury może też zmienić politykę na żywo." (chwyt: zapraszamy do ataku — to odwraca role i wygląda pewnie)

### „Skąd wiemy, że testy nie testują samych siebie?"
**„Oczekiwane wyniki są spisane w YAML niezależnie od implementacji** — 106 case'ów treściowych plus 17 red-team probe'ów (`make redteam-live`) napisanych tak, by próbowały obejść system, nie potwierdzić go. Deterministyczne testy są stabilne w CI; semantyczne mają mock, żeby wynik nie zależał od humoru modelu."

---

## F. Pytania-pułapki (przygotowane kompromisy)

### „Dlaczego mock/heuristic w /health zamiast prawdziwego modelu?"
**„Degradacja kontrolowana: bez skonfigurowanego LLM warstwa semantyczna przechodzi na lokalny heuristic scorer, a KAŻDA inna kontrola działa bez zmian — to jest właśnie test odporności, nie ukrywany brak.** Na demo produkcyjnym ustawiamy `LLM_BASE_URL` na GB10/OpenRouter jednym wpisem w .env. (Jeśli jury dociska: pokazujemy `make run` z OpenRouter — 1 zmienna.)"

### „OCR i 10+ formatów — to nie jest(scope creep)?"
**„To jest odpowiedź na LLM01 w praktyce: instrukcja siedzi tam, gdzie człowiek nie czyta — metadane PDF, ukryty wiersz Worda, biały tekst 1-pt, notatki spikera, EXIF, ukryty arkusz.** Bez parsowania tych warstw 'firewall promptów' to marketing. Aktywna zawartość (JS, makra, DDE, zdalne szablony) jest blokowana osobną regułą DOC-001."

### „A po co wam dwa GB10?"
**„Tensor parallel dla modelu-strażnika — lokalnie, stały koszt, zero round-tripów do chmury; confidencjalne prompty nie opuszczają budynku.** Ale uwaga: Aegis działa też bez nich — jakikolwiek serwer OpenAI-compatible. GB10 to nasza instalacja referencyjna, nie wymóg."

### „Kto w banku to wdroży? To zmienia proces."
**„Właśnie o to chodzi: security dostaje JEDEN plik polityki zamiast negocjacji z każdym zespołem agentowym.** Zespół integruje się przez base_url w godzinę, security egzekwuje reguły centralnie i na żywo, audyt ma dowód na każdą decyzję. Adoptowalność jest celowo większa niż innowacyjność — drop-in, nie rewolucja procesowa."

---

## Ściągawka liczb (mówić tylko te, wszystkie z repo)
| Co | Wartość | Gdzie sprawdzić na żywo |
|---|---|---|
| Testy automatyczne | **334** (pozytywne+negatywne) | `make test-docker` |
| Case'y treściowe / red-team | 106 YAML / 17 probe'ów | `make redteam-live` |
| Sprawdzenie treści p50 | **0,36 ms** | `/metrics` |
| Pełna decyzja BLOCK | **2,3 ms** | `/metrics` |
| Zatrzymanie evil.com mail | **0,7 ms** (`MANDATE-RCPT`) | scenariusz w dashboardzie |
| Maile po blokadzie | **0** | licznik usługi pocztowej |
| Overspend przy 30 agentach | **0 tokenów** | przycisk w dashboardzie |
| Etapów pipeline | **10**, pierwszy BLOCK kończy | slajd 3 |
| Głębokość delegacji | ≤ 3, poufność dziedziczona | `make demo` |
| Hot-reload polityki | < 1 s, wersje + rollback | dashboard → Konfiguracja |

**Anty-wzorce (NIE robić):**
- Nie mówić „zawsze" i „niemożliwe" — zamiast tego „testowaliśmy X, taka jest granica".
- Nie wchodzić w spór o Model-Safety-philosophy; kotwica: „uprawnienia to nie NLP".
- Nie odpowiadać dłużej niż 45 s na pytanie — detal zawsze można dołożyć.
- Nie kłamać w liczbach: każda liczba w ustach musi mieć źródło w repo/metrykach.

# Aegis — FAQ i ściąga na pytania jury

Krótko i na temat. Liczby pochodzą z kodu i z pomiarów, linki do źródeł są na końcu.

---

## Jak to działa (30 sekund)

1. Aplikacja tworzy **zadanie** i dostaje dla agenta **przepustkę** (lease podpisany HMAC). Przepustka jest powiązana z agentem, użytkownikiem i zadaniem.
2. Zadanie ma **mandat**, czyli listę tego, co agent może zrobić:
   - jakie pliki czytać,
   - jakich narzędzi używać,
   - do kogo pisać,
   - ile wydać,
   - jak długo działać.
3. **Każde** wywołanie agenta (model, narzędzie, MCP, delegacja) idzie przez bramkę Aegis. Bramka sprawdza je **przed** wykonaniem, od najtańszej kontroli do najdroższej. Pierwsza blokada kończy sprawdzanie.
4. Dopiero potem coś się wykonuje: model na GB10, narzędzie albo kod w piaskownicy. Odpowiedź jest sprawdzana jeszcze raz, zanim trafi do agenta.
5. Każda decyzja trafia do dziennika audytu, którego baza nie pozwala zmienić.

**Jedno zdanie:** inne zabezpieczenia pytają, czy akcja *wygląda* groźnie. Aegis pyta, czy agent w ogóle *miał prawo* to zrobić, z tymi danymi i w tym zadaniu.

---

## Dlaczego to jest bezpieczne

- **Reguły decydują, AI tylko doradza.** O uprawnieniach decydują deterministyczne reguły. Model AI może decyzję tylko zaostrzyć, nigdy jej nie złagodzi. Oszukany detektor AI nie otworzy niczego, czego reguły nie pozwalają.
- **Fail-closed.** Gdy coś nie działa, system blokuje albo wybiera najostrzejszą opcję:
  - ocena AI niedostępna,
  - nieznane narzędzie,
  - brak etykiety dokumentu,
  - sandbox nie odpowiada.
- **Pochodzenie danych (taint).** Jeśli zadanie przeczyta coś poufnego, całe zadanie staje się poufne. Parafraza, tłumaczenie czy base64 tego nie zmieniają. Poufne dane nie wyjdą tam, gdzie wolno tylko publiczne.
- **Agent nie ma kluczy.** Dane dostępowe do narzędzi trzyma tylko bramka. Bezpośrednie wywołanie backendu kończy się `401`.
- **Dowód, a nie komunikat.** Licznik po stronie serwera poczty pokazuje, że zablokowany mail fizycznie nie wyszedł.
- **Polityki nie da się popsuć.** Błędny plik polityki jest odrzucany, a obowiązuje ostatnia dobra wersja. Każda zmiana ma wersję i da się ją cofnąć.

---

## Mechanizmy: ile bez AI, ile z AI

**W pliku polityki jest 9 kontroli: 8 deterministycznych i 1 oparta na AI.**

| # | Mechanizm | AI? | Co robi |
|---|---|---|---|
| 1 | Mandat zadania | nie | narzędzia, ścieżki plików, odbiorcy, modele, czas życia |
| 2 | Lease HMAC | nie | przepustka związana z agentem, wygasa po zakończeniu, cofnięciu albo po czasie |
| 3 | Lista dozwolonych modeli | nie | żądanie do modelu spoza listy jest odrzucane |
| 4 | Przypinanie narzędzi MCP | nie | hash definicji; zmiana po zatwierdzeniu oznacza kwarantannę |
| 5 | Sygnatury ataków | nie | 8 sygnatur w 6 typach dopasowań: regex, skan opcode'ów pickle, wersja komponentu (CVE-2024-34359), szablon GGUF, źródło modelu (typosquat), zmiana narzędzia |
| 6 | Dane osobowe | nie | 5 typów z walidacją: PESEL (suma kontrolna), karta (Luhn), IBAN (mod-97), e-mail, telefon |
| 7 | Sekrety | nie | 7 typów: klucze chmurowe, klucze prywatne, JWT, tokeny GitHub i Slack, klucze API, hasła w treści |
| 8 | Heurystyki prompt injection | nie | 6 wzorców, w tym ukryte znaczniki HTML |
| 9 | Przepływ danych (taint) | nie | poziom poufności zadania kontra poziom dopuszczenia odbiorcy |
| 10 | Escrow budżetu | nie | tokeny, wywołania i współbieżność rezerwowane z góry w 4 zakresach: zadanie, rodzic, użytkownik, globalnie |
| 11 | Piaskownica kodu | nie | jednorazowy kontener bez sieci z twardymi limitami |
| 12 | Filtr wyjścia | nie | odpowiedź modelu jest sprawdzana przed wydaniem |
| 13 | Delegacja | nie | mandat podagenta musi być podzbiorem mandatu rodzica |
| 14 | Pamięć per sprawa | nie | agent nie odczyta pamięci innego klienta |
| 15 | Audyt append-only | nie | trigger w bazie odrzuca UPDATE i DELETE |
| 16 | Wersje polityki | nie | walidacja, ostatnia dobra wersja, rollback |
| 17 | **Ocena AI (semantyczna)** | **tak** | DeepSeek V4 Flash ocenia ryzyko manipulacji. **Może tylko zaostrzyć** decyzję |

**Razem: 16 mechanizmów deterministycznych i 1 AI.** Gdy model jest niedostępny, ocenę AI zastępuje lokalny klasyfikator heurystyczny bez AI. Nawet wtedy reguły 1–16 działają w pełni.

---

## Wydajność: DeepSeek V4 Flash na dwóch GB10

| Co | Wartość | Uwagi |
|---|---|---|
| Model | DeepSeek V4 Flash, MoE, 284 mld parametrów, 13 mld aktywnych na token | FP8 |
| Sprzęt | 2× NVIDIA GB10 (DGX Spark), 2 × 128 GB pamięci zunifikowanej, połączone kablem 200 Gb/s (RoCE) | tensor parallel TP=2 |
| Generowanie, jeden strumień | **ok. 38–41 tok/s** | vLLM, FP8, TP=2 |
| Z dekodowaniem spekulatywnym | **ok. 40–60 tok/s**, do ~65 tok/s na kodzie | DSpark / MTP |
| Łącznie przy wielu żądaniach | **ok. 145 tok/s przy 16**, **ok. 350 tok/s przy 32** równoległych | throughput całego klastra |
| Czytanie promptu (prefill) | **ok. 1,6–1,8 tys. tok/s** | umowa 6 tys. tokenów ≈ 3,6 s |

**Co to znaczy dla Aegis** (szacunek z powyższych liczb):

| Operacja | Czas |
|---|---|
| Ocena AI jednego dokumentu (~1–2 tys. tokenów wejścia, ~50 tokenów odpowiedzi) | ~1,5–2,5 s |
| Odpowiedź agenta, ~300 tokenów | ~7–8 s |
| Kontrole deterministyczne całej bramki (bez modelu) | **p95 1,3 ms** (`make bench`, raport: docs/bench-report.md) |
| Piaskownica: jedno uruchomienie kodu | ~0,3–0,5 s, zmierzone |

**Uczciwie:** GB10 to maszyna "pojemnościowa", a nie "szybka". Generowanie ogranicza przepustowość pamięci. Do agentów prawniczych to wystarcza, ale do czatu na żywo dla setek osób już nie.

**Uwaga operacyjna:** sterownik NVIDIA 580.159.03 ma regresję, przez którą generowanie spada z ~38 do ~11 tok/s. Trzeba trzymać sprawdzoną wersję sterownika.

---

## Pytania, które mogą paść

### Ogólne

**Czym to się różni od zwykłego guardraila / firewalla dla AI?**
Guardrail ocenia treść. Aegis sprawdza uprawnienia zadania i pochodzenie danych, więc nie da się go "przegadać" sprytnie napisanym tekstem.

**Kto jest klientem?**
Firmy, które chcą dać agentom dostęp do poufnych danych: banki, kancelarie, ubezpieczyciele.

**Jak to się wpina w istniejącego agenta?**
Zmieniasz `base_url` z OpenAI na Aegis i dodajesz przepustkę w nagłówku. Narzędzia wołasz przez bramkę albo przez proxy MCP. Jest gotowe SDK w Pythonie (`sdk/`, `pip install ./sdk`): sync i async, typowane decyzje, osobny wyjątek na każdą odmowę.

### Bezpieczeństwo i ataki

**Co jeśli ktoś ukryje polecenie w dokumencie (prompt injection)?**
Są trzy warstwy:
1. Heurystyki wycinają podejrzany fragment.
2. Ocena AI podnosi ryzyko.
3. Nawet jeśli obie zawiodą, reguła przepływu danych nie wypuści poufnych danych na zewnątrz.

Pokazuje to scenariusz "Detektor AI przeocza atak".

**A jeśli atakujący oszuka model oceniający?**
Nic się nie otworzy. Model może tylko zaostrzyć decyzję, a uprawnienia daje mandat, nie model.

**Czy agent może podszyć się pod innego agenta albo użytkownika?**
Nie. Lease jest podpisany HMAC i powiązany z konkretnym agentem i użytkownikiem. Cudzy albo podrobiony lease jest odrzucany. Użytkownika ustala klucz aplikacji, a nie treść żądania.

**Co z parafrazą albo zakodowaniem danych w base64?**
Nie pomoże. Poufność dziedziczy całe zadanie, niezależnie od formy danych.

**Złośliwy kod od agenta?**
Uruchamia się w jednorazowym kontenerze:
- bez sieci,
- z dyskiem tylko do odczytu,
- z limitami 256 MB / pół CPU / 64 procesy / 10 s,
- bez uprawnień.

Gdy kod jest złośliwy, pada w środku. W profilu rygorystycznym kod jest całkowicie zablokowany.

**Ataki na łańcuch dostaw modeli?**
Plik modelu (pickle) jest skanowany na poziomie opcode'ów i **nigdy nie jest ładowany**. Aegis odrzuca też:
- podatny `llama-cpp-python` (CVE-2024-34359),
- złośliwy szablon GGUF,
- model z podrobionej domeny.

**Narzędzie MCP zmieni opis po zatwierdzeniu ("rug pull")?**
Hash definicji się nie zgadza, więc narzędzie trafia do kwarantanny i znika z listy dla agenta, dopóki admin nie zatwierdzi go ponownie.

**Czy można obejść bramkę i zawołać narzędzie bezpośrednio?**
Nie. Backend wymaga sekretu, który ma tylko bramka. Bez niego dostajesz `401`.

**Czy w logach nie wyciekają dane?**
Nie. Audyt zapisuje regułę, typ danych i identyfikatory, ale nie surową treść. Jest na to test.

### AI i model

**Dlaczego DeepSeek V4 Flash?**
Ma dobry stosunek jakości do kosztu. Model MoE aktywuje tylko 13 mld parametrów na token, więc mieści się i działa sensownie na dwóch GB10. Do tego jest otwarty, więc może działać u nas.

**Czemu model jest lokalnie, a nie w chmurze?**
Poufne dane klienta nie mogą wyjść z sieci firmy, a regulamin wymaga własnego setupu. Model w chmurze Aegis traktuje jako miejsce tylko dla danych publicznych.

**Co jeśli GB10 padnie?**
Kontrole oparte na AI blokują (fail-closed), a reguły deterministyczne działają dalej. Można przełączyć ocenę na lokalny klasyfikator heurystyczny.

**Czy można podmienić model?**
Tak. Wystarczy zmienić cztery zmienne środowiskowe na dowolny serwer zgodny z API OpenAI (vLLM, SGLang, llama.cpp). Kod zostaje ten sam.

### Wydajność i skalowanie

**Ile to dodaje opóźnienia?**
Kontrole deterministyczne zajmują ~11 ms (p95). Najwięcej kosztuje ocena AI (~1,5–2,5 s), dlatego działa tylko na niezaufanej treści i nie uruchamia się, gdy reguła już zablokowała.

**Czy budżet trzyma się przy wielu agentach naraz?**
Tak. Rezerwacja odbywa się w jednej transakcji Postgresa: 30 agentów walczy o jedną pulę, a przekroczenie wynosi 0. To jest test.

**Jak to skaluje?**
Bramka jest bezstanowa, a stan trzyma Postgres, więc można postawić wiele instancji. Wąskim gardłem jest przepustowość modelu, a nie bramka.

### Wdrożenie i działanie

**Jak to uruchomić?**
`cp .env.example .env && make run`. Na Coolify jest osobny plik compose z generowanymi sekretami.

**Jak zmienić regułę na żywo?**
W dashboardzie (Kontrole / Plik polityki) albo edycją `policy/policy.yaml`. Zmiana działa w około sekundę, a każda wersja jest zapisywana.

**Jak to testujecie?**
Jest **328 testów automatycznych** na prawdziwej bazie: przypadek pozytywny i negatywny dla każdej kontroli, 100 przypadków treściowych z YAML pisanych niezależnie od implementacji, 17 prób red-team z taksonomią OWASP (`make redteam`), macierz degradacji (każda kontrola wyłączana po kolei) i testy fuzzingowe (hypothesis). Komenda: `make test-docker`. Telemetria wydajności na żądanie: `make bench` (raport w `docs/bench-report.md`).

### Regulamin

**Czy używacie płatnych usług?**
Docelowo nie: model działa na naszych GB10. Do testów w trakcie hackathonu używaliśmy tego samego modelu przez OpenRouter, a przełączenie to zmiana adresu w `.env`.

---

## Trudne pytania (odpowiadamy uczciwie)

**"Taint blokuje też niewinne rzeczy."**
Tak, to świadomy wybór. Po przeczytaniu poufnego dokumentu całe zadanie jest poufne, więc czasem zablokujemy coś nieszkodliwego. Wolimy fałszywy alarm niż wyciek. Śledzenie pochodzenia na poziomie zdań to dalszy rozwój.

**"Kontener to nie pełna izolacja."**
Racja, dzieli jądro z hostem. Ograniczamy powierzchnię ataku: brak sieci, read-only, brak uprawnień, limity. Dockera dotyka tylko jedna usługa. Produkcyjnie: gVisor albo Firecracker.

**"Usługa piaskownicy ma socket Dockera."**
Tak, i dlatego jest to osobna, mała usługa z jednym zadaniem. Bramka nigdy nie ma dostępu do Dockera.

**"A jeśli DeepSeek będzie stronniczy albo zły?"**
Model nie podejmuje decyzji o uprawnieniach. Najgorszy przypadek: przepuści coś, co i tak zatrzymają reguły, albo zablokuje coś niewinnego.

**"Testy wykrywania sekretów?"**
Są: 18 przypadków w YAML pokrywa wszystkie 9 typów (klucze AWS ASIA/AKIA, klucze prywatne PEM, JWT, tokeny GitHub i Slack, klucze API sk-/AIza, connection stringi, hasła w treści PL/EN) plus negatywne look-aliki (klucz publiczny, za krótki token, JWT bez podpisu, URI bez hasła). Do tego testy jednostkowe każdego regexu i fuzzing sum kontrolnych.

**"Nie testowaliście tego na prawdziwych danych klientów."**
Zgadza się, demo działa na syntetycznych dokumentach. Mechanizmy działają tak samo na prawdziwych danych.

---

## Źródła (wydajność GB10)

- [elsung/dgx-spark-deepseek-v4-flash](https://github.com/elsung/dgx-spark-deepseek-v4-flash): 2× DGX Spark, FP8, TP=2: ~41 tok/s pojedynczo, ~350 tok/s przy 32 równoległych, prefill ~1785 tok/s
- [r0b0tlab/deepseek-v4-flash-nvfp4-gb10-benchmark](https://github.com/r0b0tlab/deepseek-v4-flash-nvfp4-gb10-benchmark): c=1 38,4 tok/s, c=16 144,6 tok/s
- [hazyumps/deepseek-v4-flash-gb10](https://github.com/hazyumps/deepseek-v4-flash-gb10): TP=2+EP, dekodowanie spekulatywne: ~40–60 tok/s, prefill ~1,6–1,8 tys. tok/s (repo oznaczone jako przestarzałe; autorzy kierują do eugr/spark-vllm-docker)
- [Forum NVIDIA: DeepSeek-V4-Flash-DSpark na 2× DGX Spark](https://forums.developer.nvidia.com/t/deepseek-v4-flash-dspark-on-2x-dgx-spark-gb10-big-single-stream-speed-boost-60-67-tok-s-1m-context-now-with-concurrency/374846?page=2): ~60–67 tok/s na kodzie

<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# Am acest buton (Check FIFO) care are in spate scriptul CXINVAUDIT; Atunci cand apas acest buton as vrea sa imi explici logica din script pt completarea textului din coloana 'Info Fifo' DOAR pentru consumuri (un exemplu CXREF=ISSUE, sau alte tranzactii de tip iesire vezi in pic3 toate tipurile de tranzactii). Dupa ce inteleg logica as vrea sa imi propui o solutie de imbunatatire a textului afisat tinand cont ca dupa cum vezi nu toate articolele au o tranzactie initiala...

Da. În scriptul atașat, mesajul din imagine apare deoarece verificarea FIFO a ieșirilor este condiționată de existența unei baze `INITIAL`. La prima ieșire fără această bază, scriptul blochează simularea pentru grupa respectivă, iar ieșirile următoare păstrează motivul blocării — chiar dacă între timp există recepții. Așadar, `BADFIFO=U` înseamnă **neconcludent**, nu „consum la preț greșit”.[^1_1]

Mai jos separ logica existentă de propunerea de îmbunătățire.

## 1. Ce verifică efectiv butonul Check FIFO

Pentru articolul, site-ul și gestiunea selectate, scriptul citește jurnalul `CXSTOCURI` și tranzacțiile-sursă. Calculează rezultatele în memorie, apoi completează `DESCRIPTION_LONGDESCRIPTION`, câmpul folosit pentru „Info FIFO”. În modul `CHECK`, nu modifică prețurile, soldurile sau straturile FIFO oficiale.[^1_1]

Pentru analiza ieșirilor sunt importante trei funcții:


| Funcție | Rol |
| :-- | :-- |
| `audit_rows()` | Reconstruiește straturile și stabilește prețul FIFO așteptat sau motivul pentru care nu poate verifica. |
| `flag()` | Stabilește `BADFIFO=Y/N/U/NA`. |
| `description_visible()` | Transformă rezultatul în textul afișat în „Info FIFO”. |

Acestea sunt etape distincte: calcul, clasificare, afișare.[^1_1]

## 2. Ce tranzacții sunt tratate ca ieșiri

Scriptul nu stabilește direcția numai din `CXREF`; folosește și semnul cantității `CXQTY`. În ramura de ieșire, implementează consumul de straturi doar pentru `ISSUE`, `TRANSFER` și `SHIPTRANSFER`, cu cantitate negativă.[^1_1]


| Tip din imaginea 3 | Tratament relevant pentru ieșiri în scriptul actual |
| :-- | :-- |
| `ISSUE` | Consum FIFO implementat pentru cantitate negativă; sursă `MATUSETRANS`. |
| `TRANSFER` | Consum FIFO implementat pe partea cu cantitate negativă; verifică și structura perechii de transfer. |
| `SHIPTRANSFER` | Consum FIFO implementat pentru ieșire; verificări suplimentare privind expedierea și recepțiile/anulările asociate. |
| `SHIPRETURN` | Nu este simulat ca o ieșire FIFO obișnuită; blochează simularea, deoarece necesită verificarea legăturii/alocării. |
| `VOIDRECEIPT` | La fel: nu este consum FIFO obișnuit implementat; blochează simularea. |
| `RETURN` | Necesită verificarea legăturii/alocării și blochează simularea. |
| `SHIPCANCEL` | Are o tratare specială pentru anularea pozitivă legată explicit de o expediere; celelalte situații ajung în blocarea pentru tip netratat. |

Prin urmare, „toate ieșirile” și „toate tipurile pentru care scriptul poate demonstra FIFO” nu sunt același lucru.[^1_1]

## 3. Logica pentru un consum ISSUE, pas cu pas

### A. Stabilește ordinea și baza de calcul

În cadrul selecției articol–site–gestiune, scriptul separă rândurile după `COMMODITYGROUP`, apoi le ordonează după:

```text
CXDOCUMENTDATE → CXREFID → CXSTOCURIID
```

Straturile de deschidere sunt construite din `INITIAL.CXCURBAL`, la prețul `INITIAL.UNITCOST`, nu din cantitatea `CXQTY` a rândului `INITIAL`. Recepțiile acceptate adaugă apoi straturi noi.[^1_1]

Există și validări care pot bloca reconstrucția: dată lipsă, ordine ambiguă, `INITIAL` după mișcări, baze inițiale nevalide sau duplicate la același preț.[^1_1]

### B. Verifică tranzacția-sursă

Pentru un `ISSUE`, scriptul găsește `MATUSETRANS` folosind `CXREFID` și verifică, între altele:

- articolul și, când este disponibil, activul;
- tipul mișcării;
- gestiunea și site-ul;
- cantitatea semnată;
- prețul din jurnal față de `MATUSETRANS.UNITCOST`.[^1_1]

Această verificare răspunde la întrebarea:

> „Rândul din jurnal corespunde tranzacției oficiale?”

Nu răspunde încă la întrebarea:

> „Tranzacția a consumat la prețul FIFO corect?”

Un preț poate corespunde perfect cu `MATUSETRANS`, dar să fie diferit de prețul FIFO reconstruit.[^1_1]

### C. Cere obligatoriu o bază INITIAL

Condiția care produce mesajul din imagine este:

```python
if not has_opening and qty is not None and qty < -QTY_TOLERANCE:
    blocked = "Lipseste baza INITIAL; istoricul nu este declarat complet de la zero"
```

Observația importantă: această condiție se aplică și dacă înaintea ieșirii au existat recepții suficiente. Fără `INITIAL`, scriptul nu are un mecanism alternativ de acceptare a istoricului „pornit de la zero”.[^1_1]

Mai mult, după setarea lui `blocked`, rândurile următoare din aceeași grupă sunt sărite înainte de simularea FIFO:

```python
if blocked:
    record["reason"] = blocked
    continue
```

Blocarea nu se ridică automat când apare o recepție sau când soldul afișat ajunge la zero.[^1_1]

### D. Consumă straturile disponibile și calculează prețul așteptat

Dacă baza și verificările sunt valide, scriptul:

1. verifică dacă straturile disponibile acoperă ieșirea;
2. consumă din cele mai vechi straturi;
3. calculează prețul unitar așteptat din alocări;
4. îl compară cu `UNITCOST` al ieșirii.[^1_1]

Formula utilizată este:

$$
P_{\text{așteptat}}=
\frac{\sum_i q_i p_i}{|\text{CXQTY}|}
$$

Dacă ieșirea consumă mai multe straturi, rezultatul este media ponderată a straturilor consumate în ordine FIFO, nu media tuturor intrărilor. Diferența de preț este considerată semnificativă dacă depășește `0.0005`.[^1_1]

## 4. Cum construiește textul „Info FIFO”

Formatul obișnuit este:

```text
<destinatie> | <rezultat verificare> | Sursa=<ID-uri straturi> | BADFIFO=<indicator>
```

`Sursa` reprezintă `CXSTOCURIID` al straturilor consumate în simulare, nu `MATRECTRANSID` sau `MATUSETRANSID`. Apare numai când există alocări calculate.[^1_1]

### Rezultatele principale pentru ieșiri

| Situație | Text generat |
| :-- | :-- |
| Preț conform calculului | `OK: FIFO asteptat 9,410` |
| Preț diferit de calcul | `DIFERENTA: pret ...; asteptat ...; diferenta ...` |
| Calcul imposibil | `NEVERIFICAT: <motiv>` |
| Expediere compensată integral prin anulare verificată | `EXPEDIERE ANULATA: pret ...; FIFO calculat ...` |

Peste aceste mesaje există reguli de prioritate: neconcordanța cu sursa poate înlocui textul cu `DIFERENTA SURSA`, iar lipsa sau neconcordanța `CXCURBAL` poate adăuga un mesaj de sold.[^1_1]

Indicatorii au următoarea semnificație:

- `Y`: diferență de preț FIFO demonstrată, cu sursă validată și preț așteptat calculat;
- `U`: verificare neconcludentă, sursă incertă/neconformă sau problemă de sold;
- `N`: fără aceste probleme, inclusiv pentru o ieșire validată FIFO;
- `NA`: utilizat în cazurile speciale prevăzute de script.[^1_1]


### De ce apare „-” înaintea mesajului la ISSUE

În `load_inputs()`, câmpul intern `destination` este populat din `FROMSTORELOC` al sursei. Pentru `MATUSETRANS`, selecția nu include un asemenea câmp, deci destinația rămâne necompletată, iar `display_destination()` afișează `-`.

În exemplul tău, acel `-` nu este o eroare FIFO; este un câmp de afișare fără valoare.[^1_1]

## 5. Ce se întâmplă în exemplul tău

Pentru primul consum vizibil, din `10.01.2026`, scriptul ajunge la următorul rezultat:

```text
Nu exista INITIAL acceptat
          ↓
Prima iesire cu cantitate negativa
          ↓
blocked = "Lipseste baza INITIAL..."
          ↓
Nu se calculeaza alocari sau pret FIFO asteptat
          ↓
NEVERIFICAT ... | BADFIFO=U
```

Recepția din `15.01.2026` nu deblochează simularea. De aceea consumurile ulterioare repetă același motiv. Acesta este comportamentul explicit al codului, nu o dovadă că toate acele consumuri sunt greșite.[^1_1]

Există și o particularitate care poate ascunde problema: pentru `SHIPRECEIPT`, funcția de afișare generează numai:

```text
FROMSTORELOC=... | INVUSEID=...
```

Prin urmare, o recepție poate părea pur informativă în coloană, deși reconstrucția FIFO din spate este blocată.[^1_1]

## 6. Propunerea mea: separăm lipsa INITIAL de imposibilitatea demonstrării FIFO

Nu aș înlocui pur și simplu mesajul cu „OK” și nici nu aș crea automat un `INITIAL` fictiv.

Propun două niveluri de îmbunătățire.

### Nivelul 1 — text mai clar, fără schimbarea verdictelor

Pentru cazul din imagine, textul poate deveni:

```text
FIFO NEVERIFICABIL: baza de deschidere necunoscuta; lipseste INITIAL | BADFIFO=U
```

Pentru ieșirile următoare, ar fi mai util să indice și punctul de blocare:

```text
FIFO NEVERIFICABIL: istoric blocat de la 10.01.2026, RefID=135583; baza de deschidere necunoscuta | BADFIFO=U
```

Dacă sursa consumului a fost verificată independent, aș afișa separat:

```text
SURSA OK | FIFO NEVERIFICABIL: baza de deschidere necunoscuta | BADFIFO=U
```

Acestea sunt propuneri de format. Avantajul este că utilizatorul vede diferența dintre „tranzacție conformă sursei” și „FIFO nedemonstrabil”, în loc să interpreteze lipsa `INITIAL` ca eroare de preț.

### Nivelul 2 — permite verificarea fără INITIAL, dar numai cu o bază demonstrată

Aș introduce o noțiune explicită de „bază a auditului”, cu următoarele variante:


| Bază disponibilă | Comportament propus |
| :-- | :-- |
| `INITIAL` valid | Păstrezi calculul actual. |
| Istoric confirmat complet, cu sold zero înaintea primei mișcări | Permiți reconstrucția din primele intrări, fără să ceri un rând `INITIAL`. |
| Sold zero confirmat la o dată ulterioară | Lași trecutul neconcludent, dar poți începe un segment nou de audit după acel punct. |
| Nicio bază confirmată | Păstrezi `BADFIFO=U`; nu inventezi prețul așteptat. |

Confirmarea ar trebui să aibă o dată de început și o justificare trasabilă, nu doar un parametru global care spune că orice articol fără `INITIAL` pornește de la zero.

Pentru un segment validat astfel, textul ar putea fi:

```text
FIFO OK: pret 9,410; calculat 9,410; baza sold zero confirmat la <data> | Sursa=<ID> | BADFIFO=N
```

Iar dacă există o diferență demonstrată:

```text
DIFERENTA FIFO: pret 9,410; calculat 9,250; abatere +0,160 | Sursa=<ID> | BADFIFO=Y
```


## 7. Atenție la soldul zero din captura ta

Nu aș folosi automat rândul din `29.01.2026`, unde apare `Sold=0,000`, drept punct de reluare.

În scriptul actual, controlul de sold folosește un registru separat pe preț, `book[cost]`. Așadar, un zero la un preț nu demonstrează singur că întregul stoc al articolului din gestiune este zero. În plus, când lipsește `INITIAL`, acest registru începe calculul mișcărilor de la zero, fără ca soldul istoric de deschidere să fie demonstrat.[^1_1]

Pentru reluarea sigură a auditului, propun să cerem confirmarea soldului total zero pe toate straturile relevante și o ordine clară a mișcărilor. Chiar și atunci, recepțiile prin transfer trebuie să treacă în continuare verificarea ieșirii din gestiunea-sursă; în codul actual există deja această dependență între gestiuni.[^1_1]

Soluția potrivită este, deci, să eliminăm dependența exclusivă de existența rândului `INITIAL`, nu cerința de a avea o bază de calcul demonstrabilă. Astfel poți verifica articolele care au pornit legitim de la zero, fără să declari corecte consumurile dintr-un istoric incomplet.

<span style="display:none">[^1_2][^1_3][^1_4][^1_5][^1_6][^1_7][^1_8][^1_9]</span>

<div align="center">⁂</div>

[^1_1]: paste-3.txt

[^1_2]: image.png

[^1_3]: image.jpg

[^1_4]: image.jpg

[^1_5]: projects.maximo.invlifofifocost.matrectrans_flow

[^1_6]: https://www.perplexity.ai/search/7df06d1d-be3f-49d5-9d70-b65635f70ec4

[^1_7]: https://www.perplexity.ai/search/2f49e698-d0a4-4289-ad14-921cffdcd421

[^1_8]: https://www.perplexity.ai/search/e4678c67-b242-426a-b6dc-06316887b680

[^1_9]: https://www.perplexity.ai/search/79fe622e-d3d7-4f0d-857d-e4f8dea3482c


---

# as vrea sa implementezi asa:

1. eliminăm dependența exclusivă de existența rândului INITIAL
2. din Info Fifo - elimina FROMSTORELOC pentru tranzactiile de tip iesire (ISSUE, etc)
3. daca NU am o tranzactie de tip INITIAL dar am imediat dupa 1 sau mai multe tranzactii succesive de tip IESIRE (ISSUE, etc) atunci info FIFO ramane asa cum este;
4. daca NU am o tranzactie de tip INITIAL dar la un moment dat am o tranzactie de INTRARE (SHIPRECEIPT, etc) as vrea ca tranzactiile urmatoare de tip IESIRE sa se raporteze la soldul si pretul tranzactiei/tranzactiilor de tip intrare ANTERIOARE iesirilor - asta inseamna ca in acest caz logica din script trebuie modificata. E clar ce ai de facut?
vreau scriptul cap coada modificat.

Da, este clar. Am pregătit scriptul **integral**, versiunea `4.2-local-inbound-basis`, în fișierul Python atașat. Este construit pornind de la scriptul tău, nu este doar un fragment de înlocuit. Am păstrat infrastructura existentă de citire, salvare prin MBO, refresh și protejare a istoricului de corecții.[^2_1]

## Logica implementată

### 1. Dacă există INITIAL

Rămâne logica existentă: construiește straturile inițiale din `INITIAL.CXCURBAL`, apoi simulează intrările și ieșirile în ordine cronologică.

### 2. Dacă nu există INITIAL și jurnalul începe cu ieșiri

Ieșirile de dinaintea primei intrări rămân neverificate, cu mesajul existent:

```text
NEVERIFICAT: Lipseste baza INITIAL; istoricul nu este declarat complet de la zero | BADFIFO=U
```

Diferența este că aceste ieșiri nu mai blochează permanent verificarea tranzacțiilor ulterioare.

Am eliminat prefixul de gestiune și separatorul aferent de pe tranzacțiile cu cantitate negativă. Astfel, nu mai apare nici acel `- |` înaintea mesajului.

### 3. Când apare o intrare fără INITIAL

Scriptul începe construirea unei baze FIFO locale din intrările anterioare ieșirilor.

Pentru prima intrare la fiecare preț, disponibilul folosit este:

$$
Q_{\text{disponibil}}=\min(\text{CXQTY},\max(0,\text{CXCURBAL}))
$$

Aceasta este interpretarea implementată pentru cerința ta privind soldul și prețul intrării:

- nu folosește automat întreaga cantitate recepționată dacă soldul rămas este mai mic;
- nu inventează stoc anterior dacă soldul este mai mare decât cantitatea intrării;
- folosește prețul intrării, verificat față de tranzacția-sursă.

Intrările ulterioare completează straturile disponibile, iar ieșirile consumă din ele în ordine FIFO.

## Cum se aplică exemplului din captura ta

| Tranzacție | Comportament implementat |
| :-- | :-- |
| `ISSUE -10`, înaintea primei intrări | Rămâne `NEVERIFICAT`, fără blocarea permanentă a jurnalului. |
| `SHIPRECEIPT +33`, sold `23`, preț `9,410` | Creează un strat local disponibil de `23` la `9,410`. |
| Ieșiri `-5`, `-5`, `-10`, `-3` | Consumă succesiv cele `23` disponibile. |
| Următoarea ieșire `-2`, fără disponibil | Rămâne neverificată din cauza stocului insuficient; înregistrează un deficit local de `2`. |
| Intrare `+13`, sold `11` | Creează disponibil de `11`, fără să scadă încă o dată deficitul deja reflectat în sold. |
| Ieșirea următoare | Este verificată folosind noul disponibil și prețul intrării. |

Pentru o ieșire verificată pe această bază, textul arată astfel:

```text
OK: FIFO asteptat 9,410; baza intrari anterioare (fara INITIAL) | Sursa=... | BADFIFO=N
```

Dacă prețul diferă:

```text
DIFERENTA: pret ...; asteptat ...; diferenta ...; baza intrari anterioare (fara INITIAL) | Sursa=... | BADFIFO=Y
```


## Distincții importante

- În modul fără `INITIAL`, verificarea este locală: compară ieșirile cu intrările anterioare din gestiunea respectivă. Nu mai condiționează acceptarea prețului unei recepții de demonstrarea FIFO din gestiunea de origine.
- Păstrează verificarea intrării față de tranzacția oficială. O sursă lipsă sau neconformă nu este acceptată automat.
- `RETURN`, `SHIPRETURN`, `VOIDRECEIPT` și anulările fără legături demonstrabile păstrează restricțiile existente. Nu le-am transformat artificial în consumuri obișnuite; scriptul inițial nu avea implementată alocarea lor completă.[^2_1]
- Pentru `SHIPRECEIPT`, textul informativ `FROMSTORELOC=... | INVUSEID=...` rămâne neschimbat. Eliminarea locației se aplică ieșirilor.
- Rezumatul poate rămâne `NECONCLUDENT` pentru întregul istoric, chiar dacă ieșirile de după intrări primesc `BADFIFO=N`. Verificarea locală nu certifică retroactiv perioada fără bază.


## Validare și instalare

Am verificat sintaxa și am rulat teste locale pentru: ieșiri înaintea primei intrări, exemplul cu recepție `33`/sold `23`, epuizarea disponibilului, reluarea după o intrare nouă, consumul din două straturi cu prețuri diferite, comportamentul cu `INITIAL` și regenerarea textului fără duplicare.

Testele algoritmice au folosit `Decimal` în locul clasei Java `BigDecimal`; nu reprezintă o execuție în Maximo/Jython.

Înlocuiește conținutul scriptului `CXINVAUDIT` cu întregul conținut al fișierului atașat și testează-l întâi în instanța de test. Am păstrat:

```python
ENTRY_MODE = "CHECK"
UPDATE_ENABLED = False
```

Prin urmare, această livrare este pentru butonul Check FIFO; nu activează corecțiile de preț sau sold.

<div align="center">⁂</div>

[^2_1]: paste-3.txt


---

# primesc aceasta eroare, e posibil ca scriptul sa fie prea lung? mai am un script in maximo care are max 1200 de linii

poti sa-l mai micsorezi? redu cat de mult liniile cu comentarii

Nu, eroarea din captură nu indică faptul că scriptul este prea lung. Mesajul **`encoding`** `declaration in Unicode string` apare în Jython când sursa este transmisă ca text Unicode și conține o declarație precum `# -*- coding: utf-8 -*-`. Eliminarea acelei declarații rezolvă acest tip de eroare.[^3_1]

Acea linie a fost adăugată de mine în fișierul anterior — îmi aparține problema.

## Varianta compactă este atașată

Am pregătit scriptul complet, cu aceeași logică 4.2, dar:

- fără declarația de encoding;
- fără comentarii, separatoare și explicații interne de tip docstring;
- fără liniile goale;
- numai cu caractere ASCII, fără diacritice în cod sau mesaje.

Rezultatul are 1.398 de linii. Nu l-am forțat sub 1.200 prin înghesuirea instrucțiunilor sau eliminarea verificărilor: asta ar reduce lizibilitatea fără să rezolve cauza erorii afișate.

Am verificat sintaxa și echivalența structurii codului executabil înainte și după compactare. Nu am executat însă compilarea în instanța ta Maximo/Jython.

## Ce trebuie să faci

Înlocuiește întregul conținut al scriptului `CXINVAUDIT` cu varianta compactă atașată. Prima linie trebuie să fie:

```python
from java.math import BigDecimal, MathContext, RoundingMode
```

Nu adăuga deasupra ei linia:

```python
# -*- coding: utf-8 -*-
```

Am păstrat `ENTRY_MODE = "CHECK"` și `UPDATE_ENABLED = False`; compactarea nu activează funcția Update FIFO.

<span style="display:none">[^3_10][^3_11][^3_2][^3_3][^3_4][^3_5][^3_6][^3_7][^3_8][^3_9]</span>

<div align="center">⁂</div>

[^3_1]: https://community.openhab.org/t/jsr223-file-encoding-jython/8787

[^3_2]: image.jpg

[^3_3]: https://docs.python.org/3/howto/unicode.html

[^3_4]: https://www.jython.org/jython-old-sites/docs/library/codecs.html

[^3_5]: https://cython.readthedocs.io/en/latest/src/tutorial/strings.html

[^3_6]: https://www.akamai.com/docs/guides/how-to-use-unicode-in-python3/

[^3_7]: https://bugs.launchpad.net/bugs/613302

[^3_8]: https://jython.readthedocs.io/en/ed1.0/sandbox/builtins/

[^3_9]: https://stackoverflow.com/questions/39142304/syntaxerror-encoding-declaration-in-unicode-string

[^3_10]: https://github.com/ipython/ipython/issues/3245

[^3_11]: https://bugs.jython.org/issue2638


---

## Sumar modificări CXINVAUDIT — versiunea 4.2

1. Am eliminat dependența exclusivă de `INITIAL`: dacă acesta lipsește, verificarea poate începe din intrările anterioare ieșirilor.
2. Ieșirile înaintea primei intrări rămân `NEVERIFICAT / BADFIFO=U`, dar nu mai blochează verificarea întregului jurnal.
3. Am introdus o **bază locală** din intrări:
    - prima intrare la fiecare preț folosește disponibilul `min(CXQTY, max(0, CXCURBAL))`;
    - intrările ulterioare completează straturile;
    - ieșirile consumă straturile în ordine FIFO și compară prețul înregistrat cu cel calculat.
4. Dacă disponibilul este insuficient, ieșirea rămâne neverificată, iar deficitul este luat în calcul la intrările următoare.
5. Am simplificat „Info FIFO” pentru ieșiri: fără prefixul de gestiune/`FROMSTORELOC` și fără `- |`. Rezultatele locale includ mențiunea `baza intrari anterioare (fara INITIAL)`.
6. Am păstrat verificările tranzacțiilor-sursă și restricțiile pentru retururi/anulări netratate. Cu `INITIAL`, logica existentă rămâne aplicabilă.[^4_1]
7. Am corectat compilarea Jython prin eliminarea declarației de encoding și am compactat scriptul la 1.398 de linii, eliminând comentariile, docstring-urile și liniile goale.

Check FIFO actualizează numai informațiile de audit; nu modifică prețurile, soldurile sau straturile oficiale. `UPDATE_ENABLED` rămâne `False`.

<div align="center">⁂</div>

[^4_1]: paste-3.txt


---

# In INFO FIFO ...ce reprezinta Sursa=251437 pentru o IESIRE?

`Sursa=251437` reprezintă **CXSTOCURIID** al rândului din jurnal pe care simularea FIFO l-a folosit ca strat pentru ieșirea respectivă — o intrare anterioară sau un `INITIAL`.

Cu alte cuvinte:

> „Conform calculului Check FIFO, această ieșire consumă din stratul provenit din rândul CXSTOCURI cu ID-ul 251437.”

Nu este `CXREFID`, `MATRECTRANSID` sau `MATUSETRANSID` și nu reprezintă o legătură oficială de consum salvată de Maximo; este proveniența calculată de audit.

Dacă ieșirea consumă din mai multe straturi, apar toate ID-urile distincte:

```text
Sursa=251437,251450
```

Pentru o ieșire verificată fără `INITIAL`, sursa indică intrarea/intrările anterioare folosite de baza locală.

---

# sursa ar trebui sa fie ID-ul INTRARII(in cazul de fata REFID= 1337299024) nu cxstocuriid

modifica scriptul si apoi spune-mi exact unde sa modific si ce...sau da-mi scriptul cap coada

Da — modificăm `Sursa` astfel încât să afișeze **CXREFID** al intrării consumate, nu `CXSTOCURIID`.

În exemplul tău, rezultatul va fi:

```text
OK: FIFO asteptat 9,410; baza intrari anterioare (fara INITIAL) | Sursa=1337299024 | BADFIFO=N
```

Sunt suficiente trei modificări în scriptul compact 4.2 pe care îl ai acum. Păstrăm separat identificatorul intern `source`, folosit de simulare, și adăugăm `source_ref_id` pentru afișare. În codul inițial, `Sursa` era construită direct din `allocation["source"]`, adică ID-ul rândului `CXSTOCURI`.[^6_1]

## 1. Adaugă RefID-ul la stratul creat din INITIAL

În funcția `audit_rows()`, caută:

```python
                    layers.append({"qty": row["balance"], "cost": cost,
                                   "source": row["id"], "priority": order(row)})
```

Înlocuiește cu:

```python
                    layers.append({"qty": row["balance"], "cost": cost,
                                   "source": row["id"],
                                   "source_ref_id": row.get("ref_id"),
                                   "priority": order(row)})
```

Păstrează indentarea din script.

## 2. Adaugă RefID-ul la stratul creat dintr-o intrare

Tot în `audit_rows()`, caută linia:

```python
                    layers.append({"qty": layer_qty, "cost": layer_cost, "source": row["id"], "priority": order(row)})
```

Înlocuiește cu:

```python
                    layers.append({"qty": layer_qty, "cost": layer_cost,
                                   "source": row["id"],
                                   "source_ref_id": row.get("ref_id"),
                                   "priority": order(row)})
```

Aceasta este modificarea care leagă stratul recepției din exemplul tău de `1337299024`.

## 3. Schimbă valoarea afișată în „Sursa”

În funcția `description_visible()`, caută blocul:

```python
    sources = []
    for allocation in record["allocations"]:
        source = txt(allocation["source"])
        if source not in sources:
            sources.append(source)
    if sources:
        parts.append("Sursa=" + ",".join(sources))
```

Înlocuiește-l integral cu:

```python
    sources = []
    for allocation in record["allocations"]:
        source_ref_id = allocation.get("source_ref_id")
        if source_ref_id is None:
            continue
        source = txt(source_ref_id).strip()
        if source and source not in sources:
            sources.append(source)
    if sources:
        parts.append("Sursa=" + ",".join(sources))
```


## După salvare

Rulează din nou `Check FIFO`, pentru regenerarea textelor existente.

- O singură intrare consumată: `Sursa=1337299024`.
- Mai multe intrări consumate: `Sursa=1337299024,1337377775`.
- Strat `INITIAL` fără `CXREFID`: nu afișează un ID fictiv și nu revine la `CXSTOCURIID`; acel strat nu contribuie la lista `Sursa`.

Aceste modificări schimbă numai identificatorul afișat. Nu schimbă ordinea FIFO, cantitățile alocate, prețul calculat sau verdictul `BADFIFO`.

<span style="display:none">[^6_2]</span>

<div align="center">⁂</div>

[^6_1]: paste-3.txt

[^6_2]: image.jpg


---

# as vrea ca la apasarea butonului Bin button(da-mi o alta pictograma care sa nu fie btn_garbage.gif) din dreptul tranzactiei ISSUE(matusetrans ID 150257) sa rulezi un nou script care sa corecteze data din cxstocuri (01.02.2026 00:00) IN 01.02.2026 00:01. ASA VA FIcu 1 secunda mai mare decat data receptiei (care e fix in aceeasi zi si la aceeasi ora01.02.2026 00:00); CE PARERE AI? DA-mi tot setupul pe care tre sa il fac...

Da, mutarea ieșirii după recepțiile din aceeași zi poate rezolva ordinea din jurnal, dar aș implementa-o ca o corecție controlată, nu ca un buton care adaugă timp la orice tranzacție.

Mai întâi, o precizare: `01.02.2026 00:01` înseamnă **un minut** după `00:00`, nu o secundă.

- O secundă după recepție: `01.02.2026 00:00:01`.
- Data cerută explicit de tine: `01.02.2026 00:01:00`.

Scriptul atașat implementează a doua variantă: `00:00:00 → 00:01:00`, numai pentru `MATUSETRANSID=150257`.

## 1. Ce trebuie corectat odată cu data

În captura ta, ieșirea de `-2` apare înaintea recepțiilor de la `00:00`, iar soldurile sunt calculate în această ordine.

Dacă mutăm ieșirea după recepții, trebuie actualizate și soldurile intermediare `CXCURBAL` din jurnal. Altfel, noua ordine și soldurile existente nu mai corespund.

Pentru secvența vizibilă, rezultatul așteptat este:


| Tranzacție | Ora nouă | Sold după reordonare |
| :-- | :-- | --: |
| Recepție `+13` | `00:00:00` | 13 |
| Recepție `+17` | `00:00:00` | 30 |
| Recepție `+20` | `00:00:00` | 50 |
| Recepție `+20` | `00:00:00` | 70 |
| Recepție `+20` | `00:00:00` | 90 |
| ISSUE `-2`, RefID `150257` | `00:01:00` | 88 |
| ISSUE `-3`, din 02.02.2026 | Neschimbată | 85 |

Acest rezultat presupune că nu există alte mișcări între rândurile prezentate.

Prin urmare, scriptul atașat modifică:

- `CXDOCUMENTDATE` pe ieșirea vizată;
- `CXCURBAL` pe rândurile afectate de schimbarea ordinii, pentru același articol/site/gestiune/grupă/preț.

Nu modifică `MATUSETRANS`, `UNITCOST`, `INVBALANCES` sau `INVLIFOFIFOCOST`.

Important: aceasta este o reordonare a jurnalului personalizat. Nu dovedește că recepția a avut loc efectiv înaintea consumului și nu corectează retroactiv alocările oficiale Maximo. Aplic-o dacă aceasta este ordinea de business pe care vrei să o reflecte jurnalul.

## 2. Scriptul nou

Am atașat scriptul complet `CXFIXISSUEDATE`, fără declarație de encoding, pregătit pentru testare în Maximo.

Este limitat explicit la:


| Câmp | Valoare acceptată |
| :-- | :-- |
| Obiect primit de script | `CXSTOCURI` |
| Articol | `230690001` |
| Site | `C02` |
| Gestiune | `C0220302MON` |
| Tip | `ISSUE` |
| RefMBO | `MATUSETRANS` |
| RefID | `150257` |
| Cantitate | `-2` |
| Data inițială | `01.02.2026 00:00:00`, în fusul orar al utilizatorului |
| Data finală | `01.02.2026 00:01:00` |

Protecții incluse:

- refuză alt rând sau alt obiect transmis de buton;
- verifică dreptul utilizatorului;
- refuză modificările nesalvate în tabel;
- verifică soldurile existente înaintea recalculării;
- verifică dacă rândul-țintă s-a schimbat între citiri;
- nu mută din nou tranzacția dacă are deja ora `00:01:00`;
- oprește acțiunea dacă ieșirea are istoric de corecție de preț `CXFIFO_FIX1|`, deoarece acel istoric include și data;
- salvează data și soldurile într-o singură salvare MBO.

Scriptul este livrat inițial cu:

```python
DRY_RUN = True
```

În această stare afișează ce ar modifica, fără să salveze.

## 3. Creează mesajul folosit de script

În aplicația Database Configuration, deschide acțiunea Messages și adaugă:


| Proprietate | Valoare |
| :-- | :-- |
| Message Group | `CXFIFO` |
| Message Key | `ROWRESULT` |
| Message Value | `{0}` |
| Display Method | Message box, dacă această proprietate este disponibilă |

Acest mesaj este folosit pentru rezultatul simulării, validări și confirmarea salvării.

Scriptul îl invocă astfel:

```python
service.error("CXFIFO", "ROWRESULT", [result])
```

Mesajul de succes este afișat după salvarea MBO separată; persistența trebuie verificată în test.

## 4. Creează Automation Script cu Action Launch Point

În Automation Scripts:

1. Selectează Create → Script with Action Launch Point.
2. Completează:
| Proprietate | Valoare |
| :-- | :-- |
| Launch Point | `CXUPDFIFOROW` |
| Object | `CXSTOCURI` |
| Action | `CXUPDFIFOROW` |
| Script | `CXFIXISSUEDATE` |
| Script Language | `jython` |
| Active | Bifat |
| Log Level | `INFO`, pentru test |

3. Copiază întregul conținut al scriptului atașat.
4. Păstrează inițial `DRY_RUN = True`.

Un Action Launch Point creează/asociază o acțiune de tip Custom Class care execută scriptul în contextul obiectului configurat. În acest caz, obiectul trebuie să fie rândul `CXSTOCURI`, nu înregistrarea principală `INVENTORY`.[^7_1]

În Actions, verifică:

```text
Action: CXUPDFIFOROW
Object: CXSTOCURI
Type: Custom Class
Value: com.ibm.tivoli.maximo.script.ScriptAction
```

Dacă `CXUPDFIFOROW` există deja pentru testul tehnic din captura ta, verifică asocierea existentă înainte să creezi alta. Nu păstra două configurări concurente pentru același eveniment.

## 5. Configurează Signature Option

În Application Designer, deschide aplicația Inventory și accesează Add/Modify Signature Options.

Adaugă sau actualizează:


| Proprietate | Valoare |
| :-- | :-- |
| Option | `CXUPDFIFOROW` |
| Description | `Corectie ordine ISSUE in jurnal FIFO` |
| Visible | Bifat |
| Advanced Signature Options | `This is an action that must be invoked by the user in the UI` |

Acesta este mecanismul documentat de IBM pentru asocierea unui eveniment de coloană cu o acțiune/script.[^7_2]

În Security Groups:

1. Selectează grupul de test.
2. Deschide aplicația Inventory.
3. Acordă acces la `CXUPDFIFOROW`.
4. Salvează.
5. Ieși și reintră în Maximo pentru reîncărcarea drepturilor.

În script am folosit:

```python
APP = "INVENTOR"
OPTION = "CXUPDFIFOROW"
```

Dacă aplicația ta este o clonă cu alt ID, schimbă `APP` cu identificatorul real al aplicației.

## 6. Configurează butonul din rând

Pe coloana existentă din tabelul FIFO:


| Proprietate | Valoare |
| :-- | :-- |
| Type | `Event` |
| Event | `CXUPDFIFOROW` |
| Event Description | `Muta ISSUE dupa receptii si recalculeaza soldurile jurnalului` |
| Sortable | Debifat |
| Filterable | Debifat |
| Show Filter | Debifat |
| Signature Option, dacă este disponibilă | `CXUPDFIFOROW` |
| Target ID | Lasă inițial configurația existentă; nu introduce ID-ul înregistrării |

Nu folosi `toggledeleterow`: nu vrem să marcăm rândul pentru ștergere.

IBM documentează exact modelul copierii coloanei de ștergere și înlocuirii evenimentului cu numele acțiunii. Există și un APAR istoric privind declanșarea incorectă pe anumite rânduri, deci testează butonul pe rândul concret, nu doar pe primul rând al tabelului.[^7_2]

Scriptul verifică obiectul primit. Dacă primești:

```text
Butonul trebuie sa transmita randul CXSTOCURI, nu INVENTORY
```

nu elimina verificarea. Înseamnă că trebuie corectată legarea evenimentului la sursa de date a tabelului.

### Pictogramă diferită de coș

Pentru test, poți folosi:

```text
btn_next.gif
```

Este o pictogramă de tip săgeată, potrivită ideii de deplasare înainte; numele apare ca exemplu de imagine de buton în documentația controalelor Maximo. Verifică disponibilitatea în resursele instalării tale.[^7_3]

Pe termen lung, o pictogramă de ceas cu săgeată, de exemplu o imagine personalizată numită `cx_fifo_reorder.gif`, ar descrie mai bine acțiunea. Acest nume ar fi un fișier nou de implementat, nu o imagine standard despre care presupun că există. Imaginile de UI trebuie să existe în resursele webclient și să fie referite prin numele lor; în MAS, distribuirea lor trebuie făcută prin mecanismul de customizare al deploymentului.[^7_4]

## 7. Testare și activare

### Etapa A — simulare

Cu:

```python
DRY_RUN = True
```

apasă butonul din dreptul ieșirii `150257`.

Mesajul ar trebui să înceapă cu:

```text
SIMULARE; nimic salvat.
RefID=150257: 01.02.2026 00:00:00 -> 01.02.2026 00:01:00;
solduri de jurnal de recalculat=...
```

Verifică și faptul că apăsarea pe alt rând este refuzată.

### Etapa B — salvare efectivă

După verificarea simulării în instanța de test, modifică:

```python
DRY_RUN = False
```

Salvează scriptul și apasă din nou butonul pe rândul `150257`.

Înaintea acestei etape:

- păstrează o copie a rândurilor originale afectate;
- oprește temporar procesul care scrie/reconstruiește `CXSTOCURI` și confirmă că nu mai rulează, pentru a evita rescrierea sau modificarea concurentă a jurnalului.


### Etapa C — reverificare FIFO

După salvare, apasă Check FIFO.

Noul script nu regenerează „Info FIFO”; aceasta rămâne responsabilitatea `CXINVAUDIT`. După recalculare, ieșirea de `-2` ar trebui să poată folosi prima recepție de la `00:00`, cu:

```text
Sursa=1337377775
```

și preț așteptat `9,410`, dacă celelalte validări trec.

## Limită de validare

Am verificat sintaxa scriptului livrat, dar nu l-am executat în Maximo/Jython. În special, verifică în test transmiterea rândului apăsat, salvarea și refresh-ul tabelului. ID-ul tabelului folosit pentru refresh este cel din scriptul anterior:

```python
1792055730066
```

Dacă acel ID s-a schimbat în XML, trebuie actualizat și în scriptul nou.

<span style="display:none">[^7_10][^7_11][^7_12][^7_13][^7_14][^7_15][^7_16][^7_17][^7_18][^7_19][^7_20][^7_21][^7_22][^7_23][^7_24][^7_25][^7_26][^7_27][^7_28][^7_29][^7_30][^7_31][^7_32][^7_5][^7_6][^7_7][^7_8][^7_9]</span>

<div align="center">⁂</div>

[^7_1]: https://maximosecrets.com/2021/12/13/actions/

[^7_2]: https://www.ibm.com/support/pages/apar/IV99292

[^7_3]: https://www.scribd.com/document/71536347/Ad-01

[^7_4]: https://www.ibm.com/support/pages/how-change-toolbar-images

[^7_5]: image.jpg

[^7_6]: image.jpg

[^7_7]: https://www.ibm.com/docs/en/maximo-manage/cd?topic=components-adding-buttons-application-toolbar-common-actions-menu

[^7_8]: https://a3jgroup.com/creating-custom-dialogs-in-maximo-and-triggering-automation-scripts-for-business-logic/

[^7_9]: https://bportaluri.com/wp-content/MaximoJavaDocs7612/com/ibm/ism/script/webclient/beans/autoscript/package-summary.html

[^7_10]: https://community.ibm.com/community/user/discussion/application-designer-menu-icons

[^7_11]: https://moremaximo.com/discussion/updating-wo-status-using-mx-server-after-saving-addedupdated-matrectrans-records-in-the-receiving-receipts-application

[^7_12]: https://moremaximo.com/question/launch-automation-script-from-button-on-table-control-related-to-workorder

[^7_13]: https://ibm-maximo-dev.github.io/maximo-autoscript-documentation/introduction/components/

[^7_14]: https://maximodeploy.blogspot.com/2020/12/invokecall-any-dialog-from-automation.html

[^7_15]: https://www.objec3d.com/labdetail/lab03

[^7_16]: https://www.naviam.io/resources/blog/use-case-a-multi-select-dialog-that-triggers-an-automation-script

[^7_17]: https://www.linkedin.com/pulse/sql-query-get-maximo-auto-script-launch-point-events-v-s-puywc

[^7_18]: https://stackoverflow.com/questions/57582369/maximo-use-script-to-update-work-order-when-a-related-table-is-updated

[^7_19]: https://moremaximo.com/discussion/adding-images-for-app-customization

[^7_20]: https://www.ibm.com/support/pages/system/files/inline-files/\$FILE/LatestMaximoHotfixReadMe_7118.txt

[^7_21]: https://services.anu.edu.au/files/guidance/Maximo_Navigation.pdf

[^7_22]: https://www.ibm.com/docs/en/masv-and-l/maximo-monitor/cd?topic=data-adding-images

[^7_23]: https://www.ibm.com/docs/en/masv-and-l/maximo-manage/cd?topic=images-adding-record-image-application

[^7_24]: https://www.smilemauritius.com/skin/frontend/default/modern/images/

[^7_25]: https://device.report/m/02ede80f2b87615681af0113acfacab755a4a10b447f879da75e1a2d30ee8204.pdf

[^7_26]: https://www.lexidys.com/skin/frontend/default/default/images/

[^7_27]: https://community.ibm.com/community/user/viewdocument/conditionally-changing-user-interfa?CommunityKey=3d7261ae-48f7-481d-b675-a40eb407e0fd\&tab=librarydocuments

[^7_28]: https://www.slideshare.net/slideshow/aspnet-20-projektowanie-aplikacji-internetowych/1672546?nway-=

[^7_29]: https://qmstores.com/skin/frontend/default/lingerie-pink/images/

[^7_30]: https://github.com/ibm-maximo-dev/maximo-scripting/blob/master/samples/sample05/pic2.png

[^7_31]: https://github.com/vladmandic/sdnext/blob/c9e21a51/modules/ui_sections.py

[^7_32]: https://github.com/IBM/MaximoForgeViewerPlugin/blob/master/applications/maximo/maximouiweb/webmodule/webclient/BIMField/viewer.jsp


---

# SCRIPTUL si launchpoint au acelasi cod: CXUPDFIFOROW

AM RULAT ...and now what?

Ai rulat cu succes **simularea**. Mesajul confirmă că scriptul a identificat ieșirea `150257`, propune mutarea de la `00:00:00` la `00:01:00` și a găsit 6 solduri de jurnal de recalculat. Nu s-a salvat încă nimic.[^8_1]

Faptul că scriptul și launch point-ul se numesc ambele `CXUPDFIFOROW` nu necesită schimbări pentru următorul pas.

## 1. Activează salvarea

În Automation Scripts, deschide scriptul `CXUPDFIFOROW`.

Caută:

```python
DRY_RUN = True
```

Înlocuiește cu:

```python
DRY_RUN = False
```

Salvează scriptul. Nu modifica launch point-ul sau evenimentul butonului.

Înainte de execuție, păstrează o copie a rândurilor afectate și asigură-te că procesul care reconstruiește `CXSTOCURI` nu rulează concomitent.

## 2. Apasă din nou săgeata pe ieșirea 150257

Revino în Inventory și apasă butonul din dreptul:

```text
CXREF    = ISSUE
CXREFMBO = MATUSETRANS
RefID    = 150257
Cantitate = -2
```

De această dată, rezultatul trebuie să înceapă cu:

```text
SALVAT.
```

Nu cu `SIMULARE`.

Cele 6 solduri identificate în simulare corespund rezultatului așteptat pentru secvența din imagine:


| Rând | Sold existent | Sold după corecție |
| :-- | --: | --: |
| Recepție `1337377775`, `+13` | 11 | 13 |
| Recepție `1337377778`, `+17` | 28 | 30 |
| Recepție `1337378091`, `+20` | 48 | 50 |
| Recepție `1337378096`, `+20` | 68 | 70 |
| Recepție `1337378097`, `+20` | 88 | 90 |
| Ieșire `150257`, `-2` | -2 | 88 |

Ieșirea va avea data `01.02.2026 00:01:00`, după cele cinci recepții. Soldul ieșirii din `02.02.2026`, de `85`, nu trebuie schimbat pentru această reordonare.

## 3. Rulează Check FIFO

După mesajul `SALVAT`, apasă `Check FIFO` pentru regenerarea coloanei „Info FIFO”.

Pentru ieșirea `150257`, rezultatul așteptat, dacă toate validările trec, este:

```text
OK: FIFO asteptat 9,410; baza intrari anterioare (fara INITIAL) | Sursa=1337377775 | BADFIFO=N
```

Prima ieșire din `10.01.2026` rămâne neverificată — această corecție nu îi schimbă situația.

## 4. Încheie testul în siguranță

După confirmarea rezultatului, poți pune din nou:

```python
DRY_RUN = True
```

Aceasta dezactivează salvările ulterioare prin buton, fără să anuleze corecția deja salvată. Scriptul rămâne oricum limitat la tranzacția pilot `150257`.

<div align="center">⁂</div>

[^8_1]: image.jpg


---

# totul este ok, acum as vrea ca scriptul sa ruleze 'normal' pentru orice inregistrare unde apas pe sageata. da-mi varianta scriptului modificata end to end. include la inceput si o descriere a scriptului + autor Cristian Grosu

Am pregătit varianta **completă** a scriptului `CXUPDFIFOROW`, cu descrierea și autorul `Cristian Grosu` la început. Fișierul Python atașat conține întregul cod de înlocuit.

## Ce face varianta nouă

Am eliminat restricțiile pilot pentru articol, site, gestiune, RefID, cantitatea `-2` și data fixă.

Acum funcționează pe orice rând eligibil `ISSUE / MATUSETRANS` pe care apeși săgeata:

1. Preia articolul, site-ul, gestiunea, grupa, prețul și data din rândul apăsat.
2. Verifică dacă există o intrare `RECEIPT`, `TRANSFER` sau `SHIPRECEIPT` cu cantitate pozitivă, la exact aceeași dată și oră, în aceeași grupă și la același preț.
3. Mută ieșirea cu un minut mai târziu:

```text
Data inițială: 05.03.2026 00:00:00
Data nouă:     05.03.2026 00:01:00
```

4. Recalculează soldurile `CXCURBAL` afectate în aceeași partiție articol/site/gestiune/grupă/preț.
5. Salvează data și soldurile, apoi reîncarcă tabelul.

Nu modifică prețurile, tranzacțiile oficiale `MATUSETRANS`, soldurile `INVBALANCES` sau straturile `INVLIFOFIFOCOST`.

## Limite și protecții

„Orice înregistrare” înseamnă aici orice ieșire `ISSUE / MATUSETRANS`, nu orice tip de tranzacție. Intrările, `INITIAL`, transferurile, retururile și anulările sunt refuzate explicit.

În plus:

- Dacă nu există intrare la aceeași dată/oră și același preț, nu modifică nimic.
- Dacă există alte mișcări în intervalul dintre ora inițială și ora propusă, oprește acțiunea pentru analiză, în loc să le depășească automat.
- Dacă soldurile existente nu corespund ordinii curente, nu salvează.
- Dacă există modificări nesalvate sau istoric de corecție de preț pe ieșirea vizată, oprește acțiunea.
- Verifică din nou jurnalul înaintea salvării pentru a detecta modificări intervenite în timpul calculului.

Un al doilea click nu mai mută automat aceeași ieșire încă un minut: în mod normal, la noua sa dată/oră nu mai există intrarea care a justificat prima reordonare.

## Ce înlocuiești în Maximo

1. Deschide Automation Scripts → `CXUPDFIFOROW`.
2. Înlocuiește întregul conținut cu scriptul atașat.
3. Salvează.

Nu schimba launch point-ul, acțiunea, Signature Option sau evenimentul butonului. Păstrezi săgeata și configurația deja testată.[^9_1]

Scriptul este livrat pentru salvare efectivă:

```python
DRY_RUN = False
```

Pentru o simulare înaintea unei corecții noi, schimbă temporar în:

```python
DRY_RUN = True
```

La începutul fișierului sunt incluse:

```python
# SCRIPT: CXUPDFIFOROW
# AUTOR: Cristian Grosu
# DESCRIERE: Reordoneaza un ISSUE/MATUSETRANS dupa intrarile cu aceeasi
# data si ora din CXSTOCURI, prin deplasarea datei cu un minut.
```


## După fiecare corecție

Apasă `Check FIFO` pentru regenerarea „Info FIFO”, a sursei și a verdictului `BADFIFO`. Scriptul de pe săgeată actualizează data și soldurile jurnalului, nu textul auditului.

Am verificat sintaxa variantei generate; execuția acestei versiuni generalizate trebuie validată în instanța de test. Păstrează și precauția privind procesul care reconstruiește `CXSTOCURI`: acesta nu trebuie să rescrie concomitent rândurile corectate.

<div align="center">⁂</div>

[^9_1]: image.jpg


---

# as vrea sa modifici scriptul (da-l cap coada) astfel incat sa faca modificari (ora+sold in cxstocuri) - inclusiv in obiectele care au generat tranzactia (matrectrans, etc) si in tranzactiile de tip Intrare(SHIPRECEIPT, etc); in exemplul din poza as vrea sa muti matrectransid 1337462764 cu 1 minut mai tarziu fata de cea mai mare valoare de ora de la data respectiva...adica la ora 01.07.2026 00:01 adica dupa 1337464898

Am pregătit scriptul **complet**, versiunea 3.0, în fișierul Python atașat. Include descrierea și autorul `Cristian Grosu` la început.

Noua regulă este:

> Pentru articolul, site-ul și gestiunea rândului apăsat, identifică cea mai mare dată/oră din ziua respectivă, indiferent de preț, apoi mută tranzacția selectată cu un minut după acel maxim.

## 1. Rezultatul pentru exemplul tău

În secvența din imagine, cele trei recepții au ora `01.07.2026 00:00:00`.

Pentru `MATRECTRANSID=1337462764`, scriptul propune:

```text
CXSTOCURI.CXDOCUMENTDATE:
01.07.2026 00:00:00 → 01.07.2026 00:01:00

MATRECTRANS.ACTUALDATE:
01.07.2026 00:00:00 → 01.07.2026 00:01:00
```

Ordinea rezultată va fi:


| RefID | Cantitate | Preț | Data nouă |
| :-- | --: | --: | :-- |
| `1337462758` | 40 | 9,410 | 01.07.2026 00:00:00 |
| `1337464898` | 24 | 9,410 | 01.07.2026 00:00:00 |
| `1337462764` | 12 | 8,520 | 01.07.2026 00:01:00 |

Calculul maximului nu este limitat la prețul `8,520`; include și tranzacțiile la `9,410`.

Dacă există și alte rânduri din aceeași zi, pentru același articol/site/gestiune, cu o oră mai mare, scriptul folosește acel maxim — nu presupune automat că maximul zilei este `00:00`.

## 2. Ce actualizează

### În CXSTOCURI

- Modifică `CXDOCUMENTDATE` pe rândurile accesibile utilizatorului care referă aceeași tranzacție-sursă prin `CXREFMBO + CXREFID`.
- Recalculează `CXCURBAL` în partițiile afectate:

```text
ITEMNUM + SITEID + LOCATION + COMMODITYGROUP + UNITCOST
```

- Salvează numai soldurile care diferă de valorile existente.

În exemplul tău, soldul recepției de `12` la prețul `8,520` poate rămâne tot `12`: schimbarea ordinii față de recepțiile la alt preț nu schimbă obligatoriu soldul partiției sale.

### În tranzacția-sursă

| Obiect-sursă | Câmp actualizat |
| :-- | :-- |
| `MATRECTRANS` | `ACTUALDATE` |
| `MATUSETRANS` | `ACTUALDATE` |

`ACTUALDATE` reprezintă data/ora producerii tranzacției în aceste obiecte. Nu modific automat și `TRANSDATE`, deoarece nu îl tratez ca pe un simplu duplicat al datei efective.[^10_1][^10_2]

Nu modifică expedierea-părinte a unui `SHIPRECEIPT`. Mutarea recepției `1337462764` nu justifică mutarea automată a `SHIPTRANSFER` de care este legată.

## 3. Tipurile acceptate

Scriptul permite reordonarea pentru:


| RefMBO | Tipuri acceptate |
| :-- | :-- |
| `MATRECTRANS` | `RECEIPT`, `TRANSFER`, `SHIPTRANSFER`, `SHIPRECEIPT`, `RETURN`, `VOIDRECEIPT`, `SHIPRETURN`, `SHIPCANCEL` |
| `MATUSETRANS` | `ISSUE`, `RETURN` |

Acceptarea acestor tipuri pentru schimbarea datei nu înseamnă că `CXINVAUDIT` poate demonstra FIFO pentru toate. Restricțiile auditului privind retururile și anulările rămân separate.

Nu am inclus:

- `INITIAL`: nu are o tranzacție-sursă oficială echivalentă.
- `INVTRANS`: obiectul este documentat ca read-only după creare. Nu am introdus o actualizare SQL care să ocolească această restricție.[^10_3]

Prin urmare, „etc.” este implementat prin lista explicită de mai sus, nu prin modificarea arbitrară a oricărui obiect indicat în `CXREFMBO`.

## 4. Protecții incluse

Scriptul oprește modificarea dacă:

- jurnalul are modificări nesalvate;
- tranzacția-sursă lipsește sau nu corespunde jurnalului;
- `CXDOCUMENTDATE` diferă deja de `ACTUALDATE`;
- cantitatea sau prețul nu corespund sursei;
- soldurile existente nu corespund ordinii curente;
- există istoric `CXFIFO_FIX1|` pe un rând care trebuie mutat;
- maximul zilei plus un minut ar trece în ziua următoare;
- mutarea unei expedieri ar plasa-o după o recepție/anulare legată;
- sursa sau jurnalul s-au modificat între citirile de verificare.

Sursa este încărcată ca MBO înrudit cu rândul din setul de jurnal salvat, pentru a participa la aceeași tranzacție MBO, în loc de două salvări independente. Acesta este modelul recomandat pentru MBO-uri înrudite.[^10_4]

## 5. Cum îl instalezi

Păstrezi configurația existentă:

```text
Script:       CXUPDFIFOROW
Launch Point: CXUPDFIFOROW
Action:       CXUPDFIFOROW
Object:       CXSTOCURI
Event:        CXUPDFIFOROW
Message:      CXFIFO / ROWRESULT
```

Înlocuiești întregul conținut al scriptului cu fișierul atașat.

Această versiune este livrată inițial cu:

```python
DRY_RUN = True
```

Am revenit intenționat la simulare, deoarece acum modificăm și tranzacțiile oficiale, nu doar jurnalul personalizat.

### Testul pentru recepția 1337462764

1. Apasă săgeata de pe recepția respectivă.
2. Verifică mesajul de simulare: data propusă trebuie să fie `01.07.2026 00:01:00`, dacă nu există alte ore mai mari în ziua respectivă.
3. După validarea în instanța de test, schimbă:

```python
DRY_RUN = False
```

4. Salvează scriptul și apasă din nou săgeata.
5. Verifică atât `CXSTOCURI.CXDOCUMENTDATE`, cât și `MATRECTRANS.ACTUALDATE`.
6. Rulează `Check FIFO`.

## 6. Două limite importante

### Fiecare click este o nouă reordonare

Noua regulă diferă de versiunea anterioară. Dacă apeși din nou pe o tranzacție deja mutată, aceasta poate fi mutată încă o dată după noul maxim al zilei. Este comportamentul explicit al regulii „maximul zilei + un minut”.

### Nu reconstruiește FIFO-ul oficial

Scriptul nu conține actualizări explicite pentru `INVBALANCES`, `INVLIFOFIFOCOST`, `COSTDATE`, prețuri sau perioade financiare. Mutarea datei nu reface automat alocările FIFO istorice oficiale.

Totuși, salvarea unui `MATRECTRANS` are logică proprie și poate implica obiecte înrudite; documentația clasei menționează inclusiv posibile actualizări de inventar/cost la salvare. De aceea, nu pot garanta absența efectelor secundare ale claselor și scripturilor locale fără test în instanța ta.[^10_1]

Am verificat sintaxa fișierului generat, nu execuția lui în Maximo/Jython. Testează prima salvare cu procesul de reconstruire `CXSTOCURI` oprit și verifică și soldurile/straturile oficiale înainte și după.

<span style="display:none">[^10_10][^10_11][^10_12][^10_13][^10_14][^10_15][^10_16][^10_17][^10_18][^10_19][^10_20][^10_21][^10_22][^10_23][^10_24][^10_25][^10_26][^10_27][^10_28][^10_29][^10_30][^10_5][^10_6][^10_7][^10_8][^10_9]</span>

<div align="center">⁂</div>

[^10_1]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/app/inventory/MatRecTrans.html

[^10_2]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/app/inventory/MatUseTrans.html

[^10_3]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/app/inventory/InvTrans.html

[^10_4]: https://ibm-maximo-dev.github.io/maximo-autoscript-documentation/bestpractice/overview/

[^10_5]: image.jpg

[^10_6]: https://www.ibm.com/mysupport/aCIKe000000XeLj

[^10_7]: https://www.ibm.com/mysupport/s/defect/aCIKe000000XeLj/dt394743?language=es_MX

[^10_8]: https://maximosecrets.com/2020/07/03/a-summary-of-the-financial-processes-in-inventory-usage/

[^10_9]: https://moremaximo.com/discussion/issue-current-item-automation-script-problem

[^10_10]: https://www.linkedin.com/posts/sachinkrgupta-maximo-consultant_hi-ibm-maximo-team-once-again-i-have-brought-activity-7349437698945814528-pZUu

[^10_11]: https://moremaximo.com/question/automation-script-debug

[^10_12]: https://www.linkedin.com/posts/sachinkrgupta-maximo-consultant_ibmmaximo-maximomas-ibmmas-activity-7469226952302936064-YTWF

[^10_13]: https://eam-maximodev-tehcnofunctional.blogspot.com/2022/04/maximo-automation-script-key-features.html

[^10_14]: https://community.spiceworks.com/t/create-a-report-for-transaction-item-in-maximo/941028

[^10_15]: https://moremaximo.com/discussion/automation-scripts

[^10_16]: http://nomsamatuer.blogspot.com/2018/07/

[^10_17]: https://moremaximo.com/question/matusetrans-table

[^10_18]: https://moremaximo.com/discussion/automation-script-error-writing-to-s3-bucket-in-aws-red-hat-environment

[^10_19]: https://www.ibm.com/support/pages/object-structure-best-practices-creation

[^10_20]: https://bportaluri.com/category/maximo/page/25

[^10_21]: https://community.ibm.com/community/user/discussion/field-auto-populated-vs-manually-entered

[^10_22]: https://moremaximo.com/communities/community-home/digestviewer/viewthread?GroupId=37\&MessageKey=a863dbe1-6a4e-43bc-8a2f-0d617c1961f1\&CommunityKey=784e8753-d7af-4281-8463-e86f3b5d7076

[^10_23]: https://maximodeploy.blogspot.com/2019/

[^10_24]: https://maximodevsupport.blogspot.com/search/label/MBO

[^10_25]: https://maximodeploy.blogspot.com/2021/11/

[^10_26]: https://moremaximo.com/communities/community-home/digestviewer/view-question?ContributedContentKey=69bf095f-80f8-4152-9049-42163e6e9bc8\&CommunityKey=784e8753-d7af-4281-8463-e86f3b5d7076

[^10_27]: https://gist.github.com/1c90faa6c20b28346e02

[^10_28]: https://maximodeploy.blogspot.com/2017/09/enforce-unique-key-and-fetch-records.html

[^10_29]: https://ibm-maximo-dev.github.io/maximo-autoscript-documentation/integration/osevents/

[^10_30]: https://moremaximo.com/discussion/updating-wo-status-using-mx-server-after-saving-addedupdated-matrectrans-records-in-the-receiving-receipts-application


---

# e ok, a fost ok cu dry_run=fALSE

Perfect, ai confirmat că execuția cu `DRY_RUN = False` a funcționat pentru cazul testat.

Păstrăm `CXUPDFIFOROW` versiunea 3.0 ca variantă **funcțională**, cu salvarea activă.

După fiecare reordonare, rămâne pasul `Check FIFO` pentru actualizarea „Info FIFO”, a sursei și a verdictului `BADFIFO`.

Atenție: fiecare apăsare nouă pe aceeași săgeată poate muta din nou tranzacția la maximul zilei + un minut.

---

# OK, acum as vrea sa te uiti la aceste tranzactii cu galben. Ce observi si ce propui ca si corectie ca sa fie bine din punct de vedere FIFO?

Observ o problemă de **alocare pe straturi**, nu de ordine a datelor: la 19.07.2026 s-a terminat stocul la `9,410`, dar ieșirile au continuat să fie înregistrate la acest preț, în loc să consume din stratul disponibil la `8,520`. Nu aș mai modifica datele pentru aceste rânduri.[^12_1]

## 1. Ce se întâmplă la prima tranzacție galbenă

După consumul din `18.07.2026`, în captura ta rămân:

- `2` unități la `9,410`, din recepția `1337464898`;
- `12` unități la `8,520`, din recepția `1337462764`, dacă nu există alte mișcări neafișate care afectează acest strat.[^12_1]

Următoarea ieșire, `MATUSETRANSID=209409`, consumă `3` unități. Alocarea FIFO corectă este:


| Parte din consum | Cantitate | Preț | Recepție-sursă |
| :-- | --: | --: | :-- |
| Epuizarea stratului vechi | 2 | 9,410 | `1337464898` |
| Începerea stratului următor | 1 | 8,520 | `1337462764` |

Valoarea totală corectă a consumului este:

$$
2 \times 9,410 + 1 \times 8,520 = 27,340
$$

Prețul unitar echivalent este:

$$
27,340 / 3 = 9,113333\ldots
$$

De aici apare în audit `asteptat 9,113`. Acesta este prețul echivalent al alocării din două straturi, nu prețul unei recepții.[^12_1]

## 2. Corecțiile propuse pentru cele trei ieșiri

| MATUSETRANSID | Consum | Înregistrat acum | Alocare FIFO propusă | Valoare actuală | Valoare corectă |
| :-- | --: | :-- | :-- | --: | --: |
| `209409` | 3 | 3 × 9,410 | 2 × 9,410 + 1 × 8,520 | 28,230 | 27,340 |
| `209410` | 1 | 1 × 9,410 | 1 × 8,520 | 9,410 | 8,520 |
| `209419` | 4 | 4 × 9,410 | 4 × 8,520 | 37,640 | 34,080 |
| Total | 8 |  |  | 75,280 | 69,940 |

Pentru aceste trei rânduri, valoarea consumurilor este mai mare cu `5,340` față de alocarea FIFO reconstruită.

După corecție, disponibilul teoretic ar fi:


| Preț | Cantitate rămasă |
| :-- | --: |
| 9,410 | 0 |
| 8,520 | 6 |

Aceste rezultate se referă la secvența afișată; trebuie continuată verificarea și pe tranzacțiile ulterioare.[^12_1]

## 3. Nu recomand să schimbăm pur și simplu 209409 la 9,113

Pentru prima ieșire, o simplă actualizare:

```text
MATUSETRANSID=209409
UNITCOST: 9,410 → 9,113
```

nu reprezintă complet corecția FIFO:

- ascunde faptul că au fost consumate două straturi;
- pierde precizia valorii totale dacă prețul este păstrat numai la trei zecimale;
- în `CXSTOCURI`, unde soldul este calculat pe preț, ar crea o partiție la `9,113`, deși nu există o intrare la acest preț.

IBM precizează că, atunci când un consum utilizează mai multe înregistrări de cost FIFO, Maximo creează tranzacții financiare distincte pentru înregistrările de cost utilizate. Prin urmare, alocarea pe straturi trebuie păstrată, nu înlocuită arbitrar cu un preț mediu rotunjit.[^12_2]

## 4. Soluția pe care o propun

### Pentru 209409: separare pe două straturi

La nivel de reprezentare a consumului, rezultatul trebuie să fie:

```text
ISSUE -2 la 9,410 → sursa 1337464898
ISSUE -1 la 8,520 → sursa 1337462764
```

Nu aș crea însă manual două `MATUSETRANS` printr-un simplu `add()` și nici nu aș modifica doar cantitatea rândului existent: trebuie tratate și legăturile documentului, valorile financiare și efectele asupra inventarului.

### Pentru 209410 și 209419: consum integral la 8,520

Rezultatul corect este:

```text
209410: ISSUE -1 la 8,520
209419: ISSUE -4 la 8,520
```

Și aici, schimbarea izolată a `UNITCOST` nu garantează corectarea valorilor și tranzacțiilor financiare asociate.

### Implementare controlată, în două etape

1. Construim un plan de corecție fără scrieri:
    - alocările exacte pe fiecare strat;
    - valorile înainte/după;
    - documentele și tranzacțiile financiare afectate;
    - cantitățile și valorile FIFO rămase;
    - efectele asupra ieșirilor ulterioare.
2. Alegem mecanismul de aplicare după verificarea documentelor:
    - preferabil, retur/reversare legată de consumul original și repostare prin funcționalitatea Maximo, dacă fluxul și perioada contabilă permit;
    - dacă este necesară o corecție istorică, un handler dedicat de reconciliere, care tratează împreună jurnalul, sursele, straturile și efectele financiare.

Repostarea făcută astăzi nu trebuie presupusă automat echivalentă cu refacerea consumului istoric: trebuie verificat ce straturi ar utiliza efectiv.

## 5. Ce aș corecta în jurnal

După aplicarea corecției reale, `CXSTOCURI` trebuie să reflecte alocările rezultate:

- stratul `9,410` se închide la zero;
- stratul `8,520` scade succesiv `12 → 11 → 10 → 6`;
- nu mai apare soldul negativ `-1 → -2 → -6` la `9,410`;
- prima ieșire este reprezentată coerent pe cele două prețuri, fără un strat fictiv la `9,113`.

Aș păstra butonul-săgeată exclusiv pentru reordonarea datelor și aș construi separat corecția de consum FIFO. În cazul acesta, auditul a identificat corect momentul trecerii între straturi; următorul pas este corectarea alocării, nu mutarea din nou a recepțiilor.

<span style="display:none">[^12_10][^12_11][^12_12][^12_13][^12_14][^12_15][^12_16][^12_17][^12_18][^12_19][^12_20][^12_21][^12_3][^12_4][^12_5][^12_6][^12_7][^12_8][^12_9]</span>

<div align="center">⁂</div>

[^12_1]: image.jpg

[^12_2]: https://www.ibm.com/support/pages/why-does-item-fifo-cost-cost-average-cost-time-its-consumption

[^12_3]: https://www.ibm.com/support/pages/understanding-maximo-inventory-option-maximum-number-items-created-inventory

[^12_4]: https://www.ibm.com/support/pages/maximo-support-desk-material-cost-work-order-actuals-tab-appears-be-calculated-incorrectly-lifofifo-items

[^12_5]: https://www.ibm.com/support/pages/reordering-items-inventory-application-contract

[^12_6]: https://www.ibm.com/docs/en/maximo-manage/cd?topic=inventory-costs

[^12_7]: https://www.ibm.com/support/pages/configuring-issue-costs

[^12_8]: https://www.ibm.com/docs/en/maximo-ora-con/8.1.0?topic=integration-structure-items-organizations

[^12_9]: https://www.ibm.com/docs/en/maximo-ora-con/761?topic=integration-effectivity-items

[^12_10]: https://www.ibm.com/support/pages/does-maximo-distribute-costs-against-multiple-assets

[^12_11]: https://www.ibm.com/docs/en/masv-and-l/maximo-ref/cd?topic=metrics-financial

[^12_12]: https://www.ibm.com/docs/en/maximo-ora-con/8.1.0?topic=integration-costing-method

[^12_13]: https://www.ibm.com/support/pages/return-rotating-asset-vendor

[^12_14]: https://www.ibm.com/support/pages/apar/IZ84319

[^12_15]: https://www.ibm.com/docs/en/mio?topic=reports-live-export-details-table

[^12_16]: https://www.ibm.com/support/pages/how-return-rotating-asset-storeroom-inventory-usage-using-mif

[^12_17]: https://www.perplexity.ai/search/9b6db74a-cefe-46a4-af8a-c21101860197

[^12_18]: https://www.perplexity.ai/search/43fd53ad-2982-4212-9cb1-040b68eedb1e

[^12_19]: https://www.perplexity.ai/search/8e793ea8-45eb-4a4b-a532-078ea1c6cdf5

[^12_20]: https://www.perplexity.ai/search/28dda800-8519-4a70-b23a-57cd11a51621

[^12_21]: https://www.perplexity.ai/search/2f1cef32-9802-4492-84d7-ee28be7827aa


---

# tine cont ca daca matusetransid sunt consecutive si tranzactiile au aceeasi data....sansele sunt maxime ca in realitate sa fie doar o tranzactie de consum de 4buc....iar pt ca Maximo nu a avut datele corecte fifo a facut split fifo 3 si 1buc in loc de 2buc si 2 buc

deci solutia corecta e ca in astfel de cazuri sa corectezi si cantitatea si pretul \& valoarea

Da, ai dreptate: trebuie să analizăm **consumul logic**, nu să presupunem că fiecare `MATUSETRANS` reprezintă un consum independent.

Dacă `209409` și `209410` sunt două rânduri generate pentru aceeași linie de consum de `4` unități, atunci soluția corectă este redistribuirea celor `4` unități între straturile FIFO disponibile. Propunerea mea anterioară de a împărți separat rândul `209409` nu ar mai fi necesară.

## Corecția pentru exemplul tău

Înaintea acestui consum avem, conform reconstrucției discutate:

- `2` unități disponibile la `9,410`;
- următorul strat disponibil la `8,520`.

Prin urmare, pentru un consum total de `4`, alocarea corectă este `2 + 2`, nu `3 + 1`.


| MATUSETRANSID | Cantitate actuală în jurnal | Preț actual | Cantitate propusă în jurnal | Preț propus | Valoare consum corectă, în modul |
| :-- | --: | --: | --: | --: | --: |
| `209409` | -3 | 9,410 | -2 | 9,410 | 18,820 |
| `209410` | -1 | 9,410 | -2 | 8,520 | 17,040 |
| Total | -4 |  | -4 |  | 35,860 |

Valoarea actuală a perechii este `37,640`; valoarea FIFO corectă este `35,860`. Diferența este `1,780`, fără modificarea cantității totale consumate.

Valorile din tabel sunt prezentate în modul; la aplicare trebuie păstrate convențiile de semn ale câmpurilor oficiale. `MATUSETRANS.LINECOST` este utilizat în calculele valorii consumurilor și în raportarea FIFO, deci corecția nu se poate limita la `UNITCOST`.[^13_1]

## Cum ar trebui să arate CXSTOCURI

Pentru cele două rânduri:


| RefID | CXQTY corect | UNITCOST corect | CXCURBAL corect | Sursa FIFO |
| :-- | --: | --: | --: | :-- |
| `209409` | -2 | 9,410 | 0 | `1337464898` |
| `209410` | -2 | 8,520 | 10 | `1337462764` |

Apoi, ieșirea `209419`, de `4` unități, ar consuma integral la `8,520`, iar soldul acestui strat ar deveni `6`.

## ID-urile consecutive sunt un indiciu, nu cheia de grupare

Aici aș pune o condiție obligatorie înaintea corecției automate: să demonstrăm că cele două rânduri aparțin aceleiași operațiuni.

`MATUSETRANSID` consecutive și aceeași dată sunt un indiciu bun pentru identificarea candidaților, dar nu sunt suficiente pentru a modifica în siguranță cantitățile. Două consumuri independente pot avea și ele ID-uri consecutive și aceeași oră.

Pentru confirmare trebuie verificate:

- același document și aceeași linie de consum, prin identificatorii disponibili în schema ta;
- același articol, item set, site și gestiune;
- aceeași destinație de consum: comandă de lucru/task, activ sau locație, după caz;
- aceleași dimensiuni relevante: bin, lot, condition code, unitate de măsură;
- cantitatea totală a grupului egală cu cea a liniei-sursă;
- absența retururilor sau anulărilor care schimbă cantitatea netă.

Nu aș grupa automat doar pe `INVUSEID`: un document poate conține mai multe linii, inclusiv pentru același articol.

## Regula de corecție pe care o adoptăm

Pentru viitorul handler, logica devine:

1. Identifică toate rândurile care compun aceeași linie de consum.
2. Păstrează cantitatea totală a operațiunii.
3. Reconstruiește straturile disponibile imediat înaintea consumului.
4. Redistribuie cantitățile între straturi, în ordine FIFO.
5. Corectează împreună cantitatea, prețul și valoarea fiecărui rând.
6. Sincronizează `CXSTOCURI`, recalculează soldurile afectate și verifică efectele financiare și straturile oficiale.
7. Reverifică ieșirile ulterioare.

Pentru perechea aceasta, dacă legătura cu aceeași linie de consum se confirmă, putem reutiliza cele două rânduri existente: `209409 = 2 × 9,410`, respectiv `209410 = 2 × 8,520`. Nu mai este nevoie să propunem un al treilea rând.

Așadar, corectez abordarea: unitatea de analiză și corecție va fi operațiunea de consum cu toate spliturile sale, nu fiecare `MATUSETRANS` luat separat.

<span style="display:none">[^13_10][^13_11][^13_2][^13_3][^13_4][^13_5][^13_6][^13_7][^13_8][^13_9]</span>

<div align="center">⁂</div>

[^13_1]: https://www.ibm.com/support/pages/bilog-maximo-75new-lifofifo-inventory-reports

[^13_2]: image.jpg

[^13_3]: https://www.ibm.com/support/pages/inventory-usage-updates-do-not-create-matusetrans-record

[^13_4]: https://www.ibm.com/support/pages/apar/IV54376

[^13_5]: https://www.ibm.com/support/pages/maximo-inventory-cost-type-lifofifo-causes-specific-reports-fail

[^13_6]: https://www.ibm.com/mysupport/s/defect/aCIgJ0000005Ih3/dt450729?language=pt_BR

[^13_7]: https://www.ibm.com/support/pages/why-does-item-fifo-cost-cost-average-cost-time-its-consumption

[^13_8]: https://www.ibm.com/support/pages/maximo-support-desk-material-cost-work-order-actuals-tab-appears-be-calculated-incorrectly-lifofifo-items

[^13_9]: https://maximosecrets.com/2020/07/03/a-summary-of-the-financial-processes-in-inventory-usage/

[^13_10]: https://www.linkedin.com/posts/sachinkrgupta-maximo-consultant_ibmmaximo-maximomas-ibmmas-activity-7469226952302936064-YTWF

[^13_11]: https://moremaximo.com/question/matusetrans-table


---

# uite inca un hint legat de confirmare

Da, captura asta este indiciul puternic care lipsea: `MATUSETRANS`-urile `209409` și `209410` au același **INVUSEID=62,256** și **INVUSELINEID=164,724**. Împreună însumează `-4`, deci sunt două splituri ale aceleiași linii de Inventory Usage, nu doar două tranzacții cu ID-uri consecutive și aceeași dată.[^14_1]

Se confirmă și `ACTUALDATE`-urile: prima tranzacție este la `00:00`, iar a doua la `00:01`. `TRANSDATE`-urile sunt diferite, înregistrate în octombrie, deci pentru ordinea FIFO relevantă trebuie urmărită data efectivă, nu data de procesare.

**Implicația:** pentru corecția propusă, grupăm după `INVUSEID + INVUSELINEID`, apoi păstrăm cantitatea totală `-4` și redistribuim spliturile FIFO. Dacă auditul confirmă că înainte de consum erau `2` unități la `9,410`, urmate de stratul la `8,520`, alocarea-țintă este:


| Tranzacție | Cantitate | Preț |
| :-- | --: | --: |
| Splitul `209409` | `-2` | `9,410` |
| Splitul `209410` | `-2` | `8,520` |

Înainte de actualizarea înregistrărilor oficiale, mai trebuie confirmate valorile financiare derivate — inclusiv `LINECOST` — și efectul asupra layer-urilor FIFO. Captura dovedește gruparea tranzacțiilor, dar nu validează singură fiecare valoare contabilă necesară pentru salvare.

<div align="center">⁂</div>

[^14_1]: image.jpg


---

# au si acelasi TRANSDATE

prin urmare poti sa treci sa compui acest automation script pentru corectia fifo a tranzactiilor de tip iesire: cantitate si pret
cum e mai bine? sa fac un nou buton care sa se ocupe de corectie fifo sau sa folosesc butonul si scriptul existent?

Recomand o acțiune **separată pentru corecția FIFO**, cu script nou. Nu aș adăuga această logică în săgeata `CXUPDFIFOROW`: aceea reordonează date, în timp ce noua acțiune modifică structura și valoarea consumului.

Poți reutiliza vizual butonul existent „Update FIFO”, dar trebuie să îl legăm la un script nou, nu să activăm handlerul vechi, care fusese limitat la corecții de transfer.

## 1. Despre TRANSDATE

Ai dreptate că tranzacțiile au fost procesate practic împreună. Totuși, în captura SQL se văd:

```text
209409: 2026-10-22 13:27:36.627000
209410: 2026-10-22 13:27:36.674000
```

Sunt în aceeași secundă, dar diferă cu `47` milisecunde. Prin urmare, nu voi folosi egalitatea exactă a `TRANSDATE` drept condiție de grupare.

Legătura principală rămâne:

```text
INVUSEID     = 62256
INVUSELINEID = 164724
```

`TRANSDATE`, articolul, gestiunea și destinația consumului vor fi verificări suplimentare, nu cheia principală.[^15_1]

## 2. Configurația recomandată

| Componentă | Propunere |
| :-- | :-- |
| Buton | Reutilizăm „Update FIFO” |
| Descriere afișată | `Corecteaza consum FIFO` |
| Script nou | `CXFIFOFIXISSUE` |
| Action / Launch Point | `CXFIFOFIXISSUE` |
| Obiect | `INVENTORY`, dacă păstrăm butonul de sus |
| Signature Option | `CXFIFOFIXISSUE`, cu drept separat |
| Scriptul de pe săgeată | Rămâne `CXUPDFIFOROW`, nemodificat |

Fiind un buton la nivel de Inventory, propun să proceseze prima operațiune neconformă în ordine cronologică, cu toate spliturile ei. În simulare trebuie să arate explicit documentul, linia și toate `MATUSETRANSID`-urile vizate.

Nu va corecta toate rândurile galbene dintr-o singură apăsare.

## 3. Logica noului script

Pentru cazul tău, scriptul va:

1. Identifica prima ieșire neconformă.
2. Citi toate spliturile aceleiași linii `INVUSEID + INVUSELINEID`, nu doar rândul galben.
3. Verifica dacă ele reprezintă o operațiune coerentă, fără retururi sau alte situații ambigue.
4. Reconstrui straturile FIFO disponibile înaintea începerii operațiunii.
5. Redistribui cantitatea totală între straturi.
6. Construi un plan înainte/după pentru cantități, prețuri, valori și solduri.
7. Aplica o singură corecție de operațiune, apoi cere `Check FIFO`.

Pentru prima versiune aș permite automat numai situațiile în care numărul spliturilor existente este egal cu numărul spliturilor necesare. Dacă sunt necesare rânduri suplimentare sau eliminarea unor rânduri, scriptul se oprește — nu inventează sau șterge tranzacții financiare.

## 4. Planul concret pentru perechea ta

| MATUSETRANSID | QUANTITY înainte | QUANTITY după | UNITCOST după | Valoare consum după, în modul |
| :-- | --: | --: | --: | --: |
| `209409` | -3 | -2 | 9,410 | 18,820 |
| `209410` | -1 | -2 | 8,520 | 17,040 |
| Total | -4 | -4 |  | 35,860 |

Se vor corecta împreună reprezentările din `MATUSETRANS` și `CXSTOCURI`, păstrând cantitatea totală consumată.

Dar nu este suficient să actualizăm doar `QUANTITY` și `UNITCOST`. IBM distinge între `UNITCOST`, `ACTUALCOST` și `LINECOST`; valoarea liniei depinde de costul efectiv și cantitate. Trebuie păstrate și convențiile de semn și precizia din instanța ta.[^15_2]

## 5. Înainte să livrez partea de salvare

Mai există un detaliu important în captura ta: cele două splituri au `MATRECTRANSID` diferite:

```text
209409 → 1337409157
209410 → 1337430204
```

Nu trebuie să păstrăm orbește aceste legături după schimbarea alocărilor. Trebuie stabilit ce reprezintă în instanța ta și dacă trebuie realiniate la straturile corecte. Recepțiile folosite de audit sunt altele: `1337464898` și `1337462764`.[^15_1]

Pentru a compune un script de salvare corect, nu doar unul care face coloana galbenă să dispară, am nevoie de aceste extrase:

```sql
-- Toate tranzactiile liniei, inclusiv eventuale retururi.
SELECT *
FROM MATUSETRANS
WHERE INVUSEID = 62256
  AND INVUSELINEID = 164724
ORDER BY ACTUALDATE, MATUSETRANSID;

-- Linia originala de consum.
SELECT *
FROM INVUSELINE
WHERE INVUSELINEID = 164724;

-- Legaturile existente si receptiile propuse de audit.
SELECT *
FROM MATRECTRANS
WHERE MATRECTRANSID IN (
    1337409157,
    1337430204,
    1337464898,
    1337462764
);
```

Așadar: păstrăm săgeata pentru date, reutilizăm „Update FIFO” cu un script nou pentru consumuri și construim corecția la nivelul întregii linii de consum. Extrasele de mai sus sunt necesare pentru a definitiva actualizările de valoare și de proveniență înainte de activarea salvării.

<span style="display:none">[^15_10][^15_11][^15_12][^15_13][^15_14][^15_15][^15_16][^15_17][^15_3][^15_4][^15_5][^15_6][^15_7][^15_8][^15_9]</span>

<div align="center">⁂</div>

[^15_1]: image.jpg

[^15_2]: https://www.ibm.com/support/pages/difference-matusetrans-line-cost-versus-actual-cost

[^15_3]: https://www.ibm.com/think/topics/mainframe-for-banking

[^15_4]: https://docs.oracle.com/cd/E95327_01/oroms/pdf/5/cws_help/WH14_01.htm

[^15_5]: https://docs.infor.com/csi/9.01.x/en-us/csbiolh/lsm1454144395977.html

[^15_6]: https://docs.oracle.com/cd/E68434_01/oroms/pdf/160/cws_help/WH14_01.htm

[^15_7]: https://learn.microsoft.com/en-us/dynamics365/project-operations/prod-pma/stkprojectcostinventoryconsumption

[^15_8]: https://public.dhe.ibm.com/software/tivoli_support/maximo/Maximo6/readme_mam_6.2.8.txt

[^15_9]: https://www.ibm.com/docs/en/mci/7.6.2?topic=application-inventory-costing

[^15_10]: https://www.ibm.com/support/pages/apar/IZ47390

[^15_11]: https://www.ibm.com/docs/en/order-management-sw/10.0.0?topic=ic-inventory-costing-method-2-first-in-first-out-fifo

[^15_12]: https://accountingo.org/financial/inventory/fifo-method/

[^15_13]: https://maximodeploy.blogspot.com/2015/11/inventory-issue-and-return-transactions.html

[^15_14]: https://www.scribd.com/document/355981866/Maximo-Script

[^15_15]: projects.maximo.fifo_split_correction

[^15_16]: https://www.ibm.com/support/pages/why-does-item-fifo-cost-cost-average-cost-time-its-consumption

[^15_17]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/app/inventory/MatUseTrans.html


---

# nu, vreau ca acest buton sa fie la nivel de linie, nu la nivel de obiect.

vreau sa apas, el corecteaza, apoi verific apoi apas pe alta linie unde vreau sa corecteze...etc

Da, atunci îl facem **la nivel de linie**, exact în fluxul dorit de tine:

```text
Apeși „Corectează FIFO” pe un rând ISSUE
    ↓
Scriptul identifică operațiunea și spliturile aferente
    ↓
Corectează numai acea operațiune
    ↓
Verifici rezultatul cu Check FIFO
    ↓
Apeși pe următoarea linie pe care vrei să o corectezi
```


## Configurația stabilită

| Componentă | Configurație |
| :-- | :-- |
| Buton nou | În fiecare rând din tabelul `CXSTOCURI` |
| Descriere | `Corecteaza consum FIFO` |
| Eveniment | `CXFIFOFIXISSUE` |
| Script nou | `CXFIFOFIXISSUE` |
| Action / Launch Point | `CXFIFOFIXISSUE` |
| Obiect de lansare | `CXSTOCURI`, nu `INVENTORY` |
| Săgeata existentă | Rămâne pentru modificarea datei, cu `CXUPDFIFOROW` |

Butonul de corecție nu va căuta automat prima linie galbenă și nu va procesa întregul articol.

## Ce înseamnă „corectează linia apăsată”

Rândul apăsat stabilește operațiunea de corectat. Dacă acesta aparține unui consum împărțit în mai multe splituri, scriptul trebuie să trateze împreună spliturile acelei operațiuni.

În exemplul tău:

- apeși pe rândul cu `CXREFID=209409` sau pe cel cu `CXREFID=209410`;
- scriptul identifică `INVUSEID=62256 / INVUSELINEID=164724`;
- corectează perechea `209409 + 209410`, păstrând consumul total de `4`;
- nu corectează automat ieșirea ulterioară `209419`.

Rezultatul urmărit pentru pereche rămâne:


| RefID | Cantitate după corecție | Preț după corecție |
| :-- | --: | --: |
| `209409` | -2 | 9,410 |
| `209410` | -2 | 8,520 |

Soldurile din jurnal afectate de această redistribuire trebuie recalculate și pe rândurile ulterioare, dar asta nu înseamnă corectarea automată a cantităților sau prețurilor celorlalte operațiuni.

După salvare, rulezi `Check FIFO`, verifici perechea și alegi tu următoarea linie. Aceasta este configurația pe care o folosim pentru noul script.

---

# ok, fa-mi un pdf cu pasii de implementare pentru butonul modificare data si recalculare sold iar apoi fa-mi un pdf cu pasii de implementare pt al 2lea buton de pe linie (corecteaza consum FIFO)

Am creat cele două **PDF-uri**, fiecare cu câte 4 pagini, cu autorul Cristian Grosu.

## 1. Modificare dată și recalculare solduri

Documentează implementarea butonului de linie `CXUPDFIFOROW`, pornind de la configurația existentă din captura ta. Include:[^17_1]

- scriptul, acțiunea și Action Launch Point-ul;
- Signature Option și drepturile de acces;
- proprietățile coloanei-event și pictograma `btn_next.gif`;
- regula „maximul zilei + un minut”;
- simularea, activarea salvării și verificările după execuție;
- restricțiile și pașii de recuperare.


## 2. Corectează consum FIFO

Documentează configurarea celui de-al doilea buton, separat, la nivel de rând `CXSTOCURI`, cu evenimentul propus `CXFIFOFIXISSUE`.

Include gruparea spliturilor după `INVUSEID + INVUSELINEID`, exemplul corecției `209409 / 209410` din `3 + 1` în `2 + 2`, cerințele de actualizare a cantității, prețului și valorii, precum și testele de acceptanță.

Am marcat explicit că al doilea PDF este un ghid de configurare și o specificație pentru dezvoltare: scriptul de corecție efectivă nu a fost încă livrat sau validat. Primul document descrie soluția deja testată; al doilea separă pregătirea butonului de activarea viitorului mecanism de corecție.

<div align="center">⁂</div>

[^17_1]: image.jpg


---

# da-mi si codul scriptului cap coada pt al 2lea buton cel de corectie consum fifo

Am atașat codul complet pentru `CXFIFOFIXISSUE`, cu descrierea și autorul Cristian Grosu la început.

Precizare importantă: aceasta este versiunea **PLAN-ONLY**, care calculează corecția, dar nu o salvează. Nu este încă handlerul final de corecție a tranzacțiilor oficiale și nu există un flag pe care să îl schimbi pentru activarea scrierilor.

Nu ar fi corect să îți livrez drept „corecție FIFO completă” un script care actualizează doar `QUANTITY`, `UNITCOST` și `LINECOST`, ignorând proveniența și efectele financiare. În datele tale, cele două splituri au inclusiv `MATRECTRANSID` diferite, care trebuie analizate înainte de salvare.[^18_1]

## Ce face scriptul atașat

La apăsarea butonului de pe un rând `ISSUE / MATUSETRANS`:

1. Identifică tranzacția apăsată prin `CXREFID`.
2. Citește toate spliturile cu același `INVUSEID + INVUSELINEID`.
3. Verifică articolul, item set-ul, site-ul, gestiunea și dimensiunile relevante ale consumului.
4. Verifică dacă totalul spliturilor corespunde cantității din `INVUSELINE`.
5. Reconstruiește straturile FIFO anterioare operațiunii, cu `INITIAL` sau cu baza locală din intrări.
6. Calculează distribuția corectă a cantității între prețuri.
7. Propune maparea pe rândurile existente, dacă numărul spliturilor permite.
8. Calculează soldurile `CXCURBAL` care ar trebui schimbate.
9. Afișează rezumatul și scrie planul detaliat în log, cu prefixul:

```text
CXFIFOFIXISSUE_PLAN
```


Nu apelează `setValue()` sau `save()`.

## Rezultatul urmărit pentru exemplul tău

Dacă istoricul disponibil confirmă alocarea discutată, planul va propune:


| RefID | Cantitate înainte → după | Preț înainte → după | Valoare corectă, în modul |
| :-- | :-- | :-- | --: |
| `209409` | -3 → -2 | 9,410 → 9,410 | 18,820 |
| `209410` | -1 → -2 | 9,410 → 8,520 | 17,040 |

Totalul rămâne `-4`, cu valoarea în modul `35,860`.

Scriptul semnalează și neconcordanțele dintre `CXDOCUMENTDATE` și `MATUSETRANS.ACTUALDATE`; nu le repară tacit în timpul analizei.

## Instalare pentru al doilea buton

Folosește configurația stabilită în PDF:


| Componentă | Valoare |
| :-- | :-- |
| Script | `CXFIFOFIXISSUE` |
| Action / Launch Point | `CXFIFOFIXISSUE` |
| Object | `CXSTOCURI` |
| Language | `jython` |
| Event al noii coloane | `CXFIFOFIXISSUE` |
| Signature Option | `CXFIFOFIXISSUE` |
| Log Level | `INFO`, pentru a înregistra planul detaliat |

Creează sau verifică mesajul:

```text
Message Group: CXFIFO
Message Key:   FIXISSUERESULT
Message Value: {0}
```

Păstrează săgeata `CXUPDFIFOROW` nemodificată. Copiază întregul cod atașat în noul script, fără declarație de encoding.

## Limitele acestei versiuni

- Tratează articole non-rotating, fără condition code.
- Refuză grupurile cu retururi, dimensiuni diferite sau alte mișcări intercalate între splituri.
- Nu creează și nu șterge splituri.
- Planul fără `INITIAL` este o reconstrucție locală, nu certificarea FIFO-ului oficial.
- Nu modifică încă legăturile `MATRECTRANSID`, valorile financiare sau straturile oficiale.

Am verificat sintaxa și am testat separat algoritmul pentru cazul `2 × 9,410 + 2 × 8,520`, inclusiv soldurile rezultate `0` și `10`. Nu am executat integrarea în Maximo/Jython.

Pentru a finaliza partea de salvare, trimite rezultatul rulării pe `209409`, împreună cu extrasele `MATUSETRANS`, `INVUSELINE` și cele patru `MATRECTRANS` cerute anterior. Planul singur nu demonstrează cum trebuie actualizate toate înregistrările oficiale.

<div align="center">⁂</div>

[^18_1]: image.jpg


---

# as vrea sa inteleg de ce aceste tranzactii au primit flag-ul: U

NEVERIFICAT: Iesire de jurnal lipsa, duplicata sau neconforma sursei |
BADFIFO=U

Am verificat scriptul `CXINVAUDIT` atașat. Flag-ul **U** înseamnă că verificarea este neconcludentă: scriptul nu a putut demonstra legătura dintre o recepție și ieșirea de jurnal care a generat-o. Nu înseamnă automat că prețul FIFO este greșit.[^19_1]

În cazul tău există un detaliu important: mesajul afișat pe toate `SHIPTRANSFER`-urile poate fi propagat de la o recepție anterioară, nu generat separat de fiecare expediere.

## 1. De unde provine exact mesajul

Textul:

```text
Iesire de jurnal lipsa, duplicata sau neconforma sursei
```

este generat în funcția `linked_exit()`, care verifică legătura unei intrări `SHIPRECEIPT` sau `TRANSFER` cu ieșirea din gestiunea de origine. Condiția este:

```python
if len(candidates) != 1 or len(outgoing) != (
        2 if expected_kind == "TRANSFER" else 1):
    return None, "Iesire de jurnal lipsa, duplicata sau neconforma sursei"
```

Pentru `SHIPRECEIPT`, scriptul:

1. citește `MATRECTRANS.RECEIPTREF`;
2. identifică expedierea-părinte `SHIPTRANSFER`;
3. caută în `CXSTOCURI` ieșirea corespunzătoare acelei expedieri;
4. cere să existe exact un rând de jurnal pentru expediere și să fie conform sursei.[^19_1]

Așadar, „lipsă” poate însemna și „există un rând, dar nu trece filtrele de conformitate”.

## 2. Ce verifică pentru ieșirea găsită

Funcția `peer_matches()` acceptă rândul numai dacă sunt îndeplinite toate condițiile relevante:


| Control | Condiție cerută |
| :-- | :-- |
| Referință | `CXREFID = MATRECTRANSID` al expedierii-părinte |
| Site și gestiune | Coincid cu `FROMSITEID` și `FROMSTORELOC` ale expedierii |
| Grupă | `COMMODITYGROUP` coincide cu grupa rândului de recepție analizat |
| Direcție | `CXQTY < 0` |
| Dată | `CXDOCUMENTDATE = ACTUALDATE`, exact, nu doar la minutul afișat |
| Articol și tip | Coincid cu tranzacția-sursă |
| Cantitate | Cantitatea semnată din jurnal corespunde sursei |
| Preț | Prețul corespunde sursei în toleranța scriptului |
| Activ, dacă este prezent | Trece verificarea față de sursă |

În plus, pentru un `SHIPTRANSFER`, scriptul refuză situația în care găsește mai multe rânduri `CXSTOCURI` cu aceeași referință la expediere, chiar dacă unul dintre ele este conform.[^19_1]

## 3. De ce apare mesajul pe toate expedierile din captura ta

Ai un `INITIAL`, apoi prima recepție vizibilă:

```text
28.01.2026 12:01
SHIPRECEIPT
RefID = 1337363644
Cantitate = 20
```

Ulterior, toate expedierile afișează același motiv.[^19_2]

În script există următorul mecanism:

```python
if blocked:
    record["reason"] = blocked
    continue
```

Dacă verificarea recepției de mai sus eșuează, motivul este memorat în `blocked`, iar mișcările următoare din aceeași grupă primesc acel motiv fără continuarea simulării FIFO.[^19_1]

Mai mult, pentru `SHIPRECEIPT`, afișarea este specială:

```text
FROMSTORELOC=... | INVUSEID=...
```

Aceasta ascunde verdictul intern al recepției. De aceea, recepția poate părea normală în tabel, iar prima eroare vizibilă apare abia pe expedierea următoare.[^19_1]

Prin urmare, primul candidat de investigat este recepția `1337363644` și expedierea indicată de `RECEIPTREF`, nu toate expedierile galbene luate separat. Fără datele sursă nu pot confirma încă ce verificare concretă eșuează.

## 4. Două interogări pentru identificarea cauzei

### A. Identifică expedierea-părinte a primei recepții

```sql
SELECT
    R.MATRECTRANSID AS RECEPTIE_ID,
    R.ISSUETYPE     AS TIP_RECEPTIE,
    R.RECEIPTREF    AS EXPEDITIE_REFERITA,
    R.ACTUALDATE    AS DATA_RECEPTIE,

    P.MATRECTRANSID AS EXPEDITIE_ID,
    P.ISSUETYPE     AS TIP_EXPEDITIE,
    P.ITEMNUM,
    P.FROMSITEID,
    P.FROMSTORELOC,
    P.SITEID       AS SITE_DESTINATIE,
    P.TOSTORELOC,
    P.QUANTITY     AS CANTITATE_EXPEDITIE,
    P.UNITCOST     AS PRET_EXPEDITIE,
    P.ACTUALDATE   AS DATA_EXPEDITIE,
    P.INVUSEID,
    P.INVUSELINEID
FROM MATRECTRANS R
LEFT JOIN MATRECTRANS P
    ON P.MATRECTRANSID = R.RECEIPTREF
WHERE R.MATRECTRANSID = 1337363644;
```

Aici trebuie să vedem ce `SHIPTRANSFER` a generat recepția și din ce site/gestiune a plecat.

### B. Compară toate rândurile jurnalului pentru acea expediere

```sql
WITH EXPEDITIE AS (
    SELECT RECEIPTREF AS MATRECTRANSID
    FROM MATRECTRANS
    WHERE MATRECTRANSID = 1337363644
)
SELECT
    P.MATRECTRANSID,
    P.ISSUETYPE,
    P.ITEMNUM       AS ARTICOL_SURSA,
    P.FROMSITEID,
    P.FROMSTORELOC,
    P.QUANTITY      AS QTY_SURSA,
    P.UNITCOST      AS PRET_SURSA,
    P.ACTUALDATE,

    C.CXSTOCURIID,
    C.CXREF,
    C.CXREFMBO,
    C.CXREFID,
    C.ITEMNUM       AS ARTICOL_JURNAL,
    C.SITEID        AS SITE_JURNAL,
    C.LOCATION      AS GESTIUNE_JURNAL,
    C.COMMODITYGROUP,
    C.CXQTY,
    C.UNITCOST      AS PRET_JURNAL,
    C.CXDOCUMENTDATE
FROM EXPEDITIE E
LEFT JOIN MATRECTRANS P
    ON P.MATRECTRANSID = E.MATRECTRANSID
LEFT JOIN CXSTOCURI C
    ON C.CXREFMBO = 'MATRECTRANS'
   AND C.CXREFID = P.MATRECTRANSID
ORDER BY C.SITEID, C.LOCATION, C.CXSTOCURIID;
```

Interpretare:

- `CXSTOCURIID` este `NULL`: nu există rând de jurnal pentru expedierea-părinte.
- Există mai multe rânduri: condiția de unicitate a scriptului poate eșua.
- Există un singur rând: comparăm ruta, cantitatea semnată, prețul și data exactă; apoi grupa față de recepție.


## 5. Ce nu trebuie confundat cu această eroare

În captură există și solduri negative, de exemplu `-19` sau `-12`. Ele sunt o problemă separată de ordine/completitudine a istoricului, care poate deveni relevantă după rezolvarea legăturii cu sursa. Nu sunt însă condiția care generează textul exact analizat aici.[^19_2][^19_1]

Nici lipsa `INITIAL` nu explică acest caz: în această gestiune există un rând `INITIAL` vizibil.

Concluzia: aș verifica întâi legătura `1337363644 → RECEIPTREF → CXSTOCURI` și aș îmbunătăți mesajul scriptului ca să arate separat „rând lipsă”, „număr de rânduri găsite” sau „dată/cantitate/rută neconformă”. Nu aș modifica prețuri sau date doar pentru a elimina `U`, înainte să știm care dintre aceste condiții a eșuat.

<div align="center">⁂</div>

[^19_1]: paste.txt

[^19_2]: image.jpg


---

# eu as vrea sa modifici scriptul CXINVAUDIT astfel incat sa foloseasca pentru audit FIFO doar obiectul CXSTOCURI. In cazul de mai sus, avem prima data 2 intrari si soldul ajunge la 33; Apoi avem o iesire de -13 care are si sold-ul dar si pretul unitar corecte. Ce parere ai? unde vom avea 'daune colaterale' daca folosim doar tranzactiile din obiectul CXSTOCURI?

Da, pentru scopul pe care îl urmărești acum, aș separa auditul FIFO al jurnalului de reconcilierea cu tranzacțiile oficiale. `CXINVAUDIT` poate folosi numai `CXSTOCURI` pentru a răspunde la întrebarea:

> „Pe baza intrărilor și ieșirilor înregistrate în acest jurnal, ieșirile respectă ordinea FIFO și soldurile sunt coerente?”

Aceasta este o verificare utilă, dar rezultatul trebuie numit **FIFO local**, nu confirmare că întregul inventar și toate tranzacțiile financiare Maximo sunt corecte.

## 1. În exemplul tău, prima ieșire este corectă local

Mai exact, avem o bază `INITIAL` și o recepție:


| Mișcare | Cantitate disponibilă/adăugată | Preț | Disponibil rezultat |
| :-- | --: | --: | --: |
| `INITIAL` din 05.12.2025 | 13 | 9,410 | 13 |
| `SHIPRECEIPT` din 28.01.2026 | +20 | 9,410 | 33 |
| `SHIPTRANSFER` din 01.02.2026 | -13 | 9,410 | 20 |
| Următorul `SHIPTRANSFER` | -17 | 9,410 | 3 |

În această secvență, cele două ieșiri au cantități acoperite de straturile anterioare, prețul corect și soldurile corecte. Din perspectiva exclusivă a `CXSTOCURI`, ele ar trebui să treacă auditul.[^20_1]

În scriptul actual, validarea legăturii dintre recepție și expedierea din altă gestiune poate bloca această analiză înainte să se ajungă la consumarea straturilor. Această dependență există în `linked_exit()`, `audit_network()` și ramura intrărilor din `audit_rows()`.[^20_2]

## 2. Ce câștigăm dacă folosim numai CXSTOCURI

Propunerea are câteva avantaje clare:

- o neconcordanță din gestiunea-sursă nu mai împiedică verificarea aritmetică și FIFO a gestiunii selectate;
- putem verifica jurnalul migrat chiar dacă legăturile istorice cu sursele sunt incomplete;
- identificăm separat diferențele de preț, soldurile greșite și insuficiența stocului anterior;
- auditul devine mai simplu de urmărit: fiecare verdict poate fi explicat prin rândurile din același jurnal.

În acest mod, prețul și cantitatea unei intrări sunt acceptate ca date de intrare ale analizei. Auditul verifică utilizarea lor ulterioară, nu autenticitatea lor față de `MATRECTRANS`.

## 3. Unde apar „daunele colaterale”

### A. Un jurnal coerent poate conține date greșite

Dacă o recepție din `CXSTOCURI` are cantitatea sau prețul greșit, dar ieșirile sunt calculate coerent pornind de la acea recepție, auditul local poate spune „OK”.

El nu mai detectează:

- o cantitate diferită în `MATRECTRANS`;
- un preț diferit în `MATUSETRANS`;
- o dată diferită față de `ACTUALDATE`;
- o referință la o tranzacție oficială inexistentă.

Prin urmare:

```text
FIFO local OK ≠ tranzacție oficială verificată
```


### B. Nu mai propagăm erorile de cost între gestiuni

O ieșire din gestiunea A poate fi greșită FIFO, iar recepția din gestiunea B poate prelua acel preț.

Dacă analizăm B exclusiv local, intrarea este acceptată la prețul din jurnal și ieșirile ulterioare pot trece auditul. Nu mai demonstrăm că prețul transferat din A era corect.

Aceasta ar fi o schimbare intenționată față de logica actuală de verificare în rețea.[^20_2]

### C. Retururile și anulările nu pot fi tratate doar după semnul cantității

Nu aș implementa regula:

```text
Orice cantitate pozitivă = intrare nouă obișnuită
Orice cantitate negativă = consum FIFO obișnuit
```

O anulare poate trebui să restaureze exact straturile consumate inițial. Un retur poate avea nevoie de legătura cu operațiunea originală.

Dacă informațiile necesare nu există în `CXSTOCURI`, aceste cazuri trebuie să rămână `U`, cu un motiv explicit. Scriptul actual folosește date din surse pentru tratarea anulărilor verificabile; eliminarea surselor înseamnă că pierdem și această demonstrație.[^20_2]

### D. Nu mai putem identifica sigur grupurile de splituri

Pentru corecția discutată anterior, gruparea corectă se bazează pe:

```text
INVUSEID + INVUSELINEID
```

Citirea actuală a `CXSTOCURI` nu include aceste câmpuri; scriptul le obține, unde sunt disponibile, din tranzacțiile-sursă.[^20_2]

Auditul local poate calcula prețul echivalent așteptat pentru fiecare rând, dar nu trebuie să decidă singur că două ieșiri reprezintă aceeași linie de consum.

De aceea, butonul de corecție a consumurilor trebuie să continue să citească obiectele oficiale, chiar dacă `Check FIFO` devine exclusiv local.

### E. Nu mai reconciliem stocul și valoarea oficială

Dacă eliminăm și citirile din `INVBALANCES` și `INVLIFOFIFOCOST`, nu mai putem verifica:

- soldul curent oficial;
- cantitățile rămase pe straturile oficiale;
- valoarea oficială a stocului.

Putem calcula doar soldul și straturile teoretice rezultate din jurnal. Scriptul actual face și aceste comparații externe în sumar; ele trebuie eliminate din verdictul local sau prezentate separat.[^20_2]

## 4. Ce trebuie păstrat strict chiar și într-un audit local

### Ordinea mișcărilor

Ordinea propusă rămâne:

```text
CXDOCUMENTDATE → CXREFID → CXSTOCURIID
```

Dar ultimele două câmpuri sunt criterii tehnice de departajare, nu dovezi despre ordinea reală a operațiunilor. În special, `CXREFID` provenite din obiecte diferite nu reprezintă neapărat o numerotare cronologică comună.

Nu aș pune automat intrările înaintea ieșirilor la aceeași oră doar pentru a elimina soldurile negative.

### Calculul straturilor, separat de verificarea soldurilor

Aș păstra două calcule independente:

1. straturile FIFO, construite din `INITIAL.CXCURBAL` și din cantitățile intrărilor acceptate;
2. soldul contabil al jurnalului pe preț, verificat față de `CXCURBAL`.

Nu trebuie să folosim soldul fiecărei recepții ca o resetare a straturilor. Altfel, putem ascunde ieșiri anterioare sau dubla disponibilul.

Pentru istoricul fără `INITIAL`, regula actuală de pornire din intrări rămâne o convenție locală și trebuie etichetată ca atare.

### Insuficiența stocului anterior

În captura ta, după primele două ieșiri rămân `3`. La 01.03.2026 avem apoi:

```text
-3  → disponibil 0
-19 → disponibil insuficient
```

Recepția de `+20` din 11.03.2026 nu poate justifica retroactiv o ieșire din 01.03.2026. Chiar într-un audit exclusiv `CXSTOCURI`, acea ieșire trebuie semnalată.[^20_1]

Deci eliminarea verificărilor externe nu trebuie să transforme toate rândurile galbene în „OK”.

## 5. Cum aș modifica CXINVAUDIT

Aș stabili următorul contract:


| Componentă | Comportament propus |
| :-- | :-- |
| Date pentru reconstrucția FIFO | Numai rândurile `CXSTOCURI` din selecția auditată |
| Prețul intrărilor | Acceptat din `CXSTOCURI.UNITCOST` |
| Cantitatea intrărilor | Din `CXQTY`; baza inițială din `INITIAL.CXCURBAL` |
| Ieșiri obișnuite | Alocate pe straturile anterioare |
| Sold | Recalculat și comparat cu `CXCURBAL`, separat pe preț |
| Referințe oficiale | Folosite ca identificatori afișați, nu validate față de sursă |
| Retururi/anulări fără informații suficiente | `U`, cu motiv explicit |
| Reconciliere cu sursele și stocul oficial | În afara verdictului local |
| Actualizări făcute de audit | Numai textul rezultatului, nu cantități/prețuri |

Exemplu de text:

```text
OK FIFO LOCAL: pret asteptat 9,410; sold asteptat 20,000 | BADFIFO=N
```

Iar sumarul:

```text
Audit exclusiv CXSTOCURI.
Sursele oficiale, soldurile si straturile oficiale nu au fost verificate.
```

Nu aș seta artificial `source_status="OK"` pentru a trece verificările existente. Aș elimina dependența verdictului local de acele verificări, astfel încât „sursă neverificată” să nu fie confundat cu „sursă validată”.

## Recomandarea mea

Pentru `Check FIFO`, sunt de acord cu trecerea la audit exclusiv `CXSTOCURI`, cu verdictul explicit „FIFO local”.

Păstrăm însă o separare clară:

- `Check FIFO`: verifică jurnalul și explică alocările;
- reconcilierea cu sursele: control distinct, care nu blochează auditul local;
- corecția consumurilor: verifică în continuare sursele, spliturile și efectele financiare înainte să scrie.

Astfel rezolvăm blocarea din exemplul tău fără să prezentăm coerența jurnalului drept garanție că și toate înregistrările oficiale sunt corecte.

<span style="display:none">[^20_3][^20_4][^20_5][^20_6]</span>

<div align="center">⁂</div>

[^20_1]: image.jpg

[^20_2]: paste.txt

[^20_3]: projects.maximo.cxstocuri.mxloader_rotating

[^20_4]: https://www.perplexity.ai/search/5575ffdf-4f0f-4384-948b-cedac9f52897

[^20_5]: https://www.perplexity.ai/search/c56ea5e5-5d9b-445a-9304-ebabd7fc7c41

[^20_6]: https://www.perplexity.ai/search/f8b74654-5483-480b-9345-db8381efe0ea


---

# Modifică scriptul CXINVAUDIT pentru a folosi doar CXSTOCURI

Am modificat `CXINVAUDIT` și am atașat scriptul **complet**, versiunea `5.0-CXSTOCURI-ONLY`, cu 677 de linii și autorul Cristian Grosu.

## Ce am schimbat

Auditul citește datele necesare reconstrucției numai din `CXSTOCURI`. Înregistrarea `INVENTORY` furnizează doar articolul, site-ul și gestiunea selectate.

Față de versiunea atașată anterior, am eliminat:

- verificările față de `MATRECTRANS`, `MATUSETRANS` și `INVTRANS`;
- verificarea documentelor `INVUSE`;
- legăturile și propagarea FIFO între gestiuni;
- comparațiile cu `INVBALANCES`, `INVLIFOFIFOCOST` și numărul activelor. Acestea existau în scriptul anterior și puteau bloca auditul local.[^21_1]

Scriptul actualizează exclusiv `DESCRIPTION_LONGDESCRIPTION` — „Info FIFO”. Nu modifică date, cantități, prețuri sau solduri.

## Cum funcționează acum

- Construiește straturile inițiale din `INITIAL.CXCURBAL`.
- Adaugă intrările `RECEIPT`, `TRANSFER` și `SHIPRECEIPT`, cu cantitate pozitivă.
- Consumă straturile în ordine FIFO pentru ieșirile `ISSUE`, `TRANSFER` și `SHIPTRANSFER`.
- Verifică separat prețul FIFO și soldul `CXCURBAL`, calculat pe preț.
- Păstrează mecanismul de pornire din intrări când nu există `INITIAL`.
- Afișează în `Sursa` valoarea `CXREFID` a intrării consumate.
- Nu mai ascunde rezultatul recepțiilor în spatele textului `FROMSTORELOC / INVUSEID`. Recepțiile primesc acum un rezultat de audit local.


### Semnificația indicatorilor

| Indicator | Semnificație |
| :-- | :-- |
| `N` | Rând verificat local, fără diferențele urmărite |
| `Y` | Diferență de preț FIFO demonstrată local, cu sold verificabil |
| `U` | Verificare neconcludentă, sold lipsă/neconform, stoc insuficient sau tip netratat |
| `NA` | `INITIAL` sau cantitate zero |

O problemă de sold are prioritate și produce `U`, chiar dacă există și o diferență de preț.

## Rezultatul pentru exemplul tău

Am testat algoritmul pentru secvența:

```text
INITIAL       13 la 9,410 → disponibil 13
SHIPRECEIPT  +20 la 9,410 → disponibil 33
SHIPTRANSFER -13 la 9,410 → disponibil 20
SHIPTRANSFER -17 la 9,410 → disponibil 3
```

Cele două expedieri primesc `BADFIFO=N`.

În schimb, dacă urmează `-3`, apoi `-19`, prima închide disponibilul, iar a doua primește `U` pentru stoc insuficient. Cu o bază `INITIAL`, această insuficiență blochează conservator simularea mișcărilor următoare din aceeași grupă; recepțiile viitoare nu justifică retroactiv ieșirea.

Retururile și anulările fără informații suficiente pentru refacerea alocării rămân, de asemenea, `U`.

## Instalare

1. Păstrează o copie a scriptului existent.
2. Deschide Automation Scripts → `CXINVAUDIT`.
3. Înlocuiește întregul conținut cu fișierul atașat.
4. Păstrează launch point-ul și butonul `Check FIFO` existente.
5. Salvează și rulează `Check FIFO` pe articolul din exemplu.

Am păstrat:

```text
Mesaj:   CXCHECKFIFO / RESULT
ID tabel: 1792055730066
```

Nu modifica scripturile separate `CXUPDFIFOROW` și `CXFIFOFIXISSUE`. Noua versiune `CXINVAUDIT` conține numai auditul local, fără handlerul vechi de Update FIFO.

Am verificat sintaxa și am testat separat calculul cu `INITIAL`, pornirea fără `INITIAL`, consumul din mai multe straturi, insuficiența stocului, soldurile neconforme și regenerarea textului. Integrarea MBO/Jython trebuie confirmată în instanța ta.

Rezumatul afișează explicit: „Sursele, stocul și straturile oficiale NU au fost verificate.”

<div align="center">⁂</div>

[^21_1]: paste.txt


---

# poti sa imi confirmi ca avem in mesajul de la sfarsit al audit fifo si o nota referitor stoc\&pret unitar din cxstocuri versus cantitate si pu din invlifofifo?

Nu. În versiunea **5.0-CXSTOCURI-ONLY**, mesajul final nu mai conține comparația dintre `CXSTOCURI` și `INVLIFOFIFOCOST`. Am eliminat-o odată cu citirile din celelalte obiecte, conform cerinței de audit exclusiv `CXSTOCURI`.

Mesajul afișează acum soldul calculat din jurnal și nota:

```text
Sursele, stocul si straturile oficiale NU au fost verificate.
```


## Cum putem păstra și comparația dorită

Putem adăuga la sfârșit o reconciliere informativă separată, fără să influențeze verdictul FIFO local sau indicatorii `BADFIFO`.

Comparația corectă ar fi pe fiecare preț unitar:


| Din CXSTOCURI | Din INVLIFOFIFOCOST |
| :-- | :-- |
| Soldul final al jurnalului la acel `UNITCOST` | Suma `QUANTITY` la același `UNITCOST` |

Important: în `CXSTOCURI` nu însumăm toate valorile `CXCURBAL`, deoarece sunt solduri succesive. Folosim soldul final pe fiecare partiție relevantă, apoi agregăm pe preț.

Un mesaj propus ar arăta astfel:

```text
Reconciliere informativa CXSTOCURI / INVLIFOFIFOCOST:
PU=9,410: sold jurnal=0,000; cantitate FIFO=0,000; diferenta=0,000.
PU=8,520: sold jurnal=6,000; cantitate FIFO=8,000; diferenta=-2,000.
Total cantitate: jurnal=6,000; FIFO=8,000; diferenta=-2,000.
Comparatia nu influenteaza verdictul FIFO LOCAL.
```

Valorile de mai sus sunt doar un exemplu de format, nu rezultate verificate în baza ta.

Astfel, reconstrucția FIFO rămâne bazată exclusiv pe `CXSTOCURI`, iar mesajul final include suplimentar comparația cu straturile oficiale. Aceasta ar necesita o citire din `INVLIFOFIFOCOST`, deci nu este inclusă în scriptul livrat acum.

---

# da, adauga aceasta comparatie informativa la sfarsitul scriptulu

Am adăugat comparația **informativă** și am atașat scriptul complet `CXINVAUDIT`, versiunea `5.1-LOCAL-RECON`.

## Ce apare acum la sfârșitul auditului

După rezumatul FIFO local, mesajul include:

- comparația cantităților pe fiecare preț unitar;
- prețurile existente numai într-unul dintre cele două obiecte;
- totalurile de cantitate;
- totalurile de valoare, calculate ca `cantitate × preț unitar`;
- diferențele, cu formula:

```text
Diferență = CXSTOCURI − INVLIFOFIFOCOST
```


Exemplu de format — valorile sunt illustrative, nu rezultate din baza ta:

```text
RECONCILIERE INFORMATIVA CXSTOCURI / INVLIFOFIFOCOST: DIFERENTE

PU=8,520: CXSTOCURI=6,000; FIFO=8,000; diferenta=-2,000 [DIFERENTA]
PU=9,410: CXSTOCURI=0,000; FIFO=0,000; diferenta=0,000 [OK]

Total cantitate: CXSTOCURI=6,000; FIFO=8,000; diferenta=-2,000.
Total valoare (cantitate x PU):
CXSTOCURI=51,120; FIFO=68,160; diferenta=-17,040.
```


## Cum se calculează comparația

| Obiect | Valoare folosită |
| :-- | :-- |
| `CXSTOCURI` | Ultimul `CXCURBAL` înregistrat pe fiecare grupă/preț, apoi agregat pe preț |
| `INVLIFOFIFOCOST` | Suma `QUANTITY` pe fiecare `UNITCOST` |

Nu însumează soldurile intermediare din jurnal.

Straturile oficiale sunt filtrate după:

```text
ITEMNUM + SITEID + LOCATION + ITEMSETID
```

Prețurile sunt comparate distinct, fără rotunjirea lor înainte de grupare.

## Ce rămâne separat

- Reconstrucția și verdictul FIFO local folosesc în continuare numai `CXSTOCURI`.
- Diferențele față de `INVLIFOFIFOCOST` nu modifică `BADFIFO`.
- Dacă citirea straturilor oficiale eșuează, mesajul indică „RECONCILIERE INFORMATIVA INDISPONIBILA”, fără invalidarea auditului local.
- Scriptul scrie numai „Info FIFO”; nu modifică solduri, cantități, prețuri sau straturi oficiale.

Comparația este agregată pe preț, nu pe bin/lot/condition code. Valorile presupun prețuri exprimate în aceeași monedă și unitate de măsură; nu se face conversie valutară.

## Instalare

Înlocuiește integral conținutul scriptului `CXINVAUDIT` cu fișierul atașat. Nu modifica butonul sau launch point-ul.

Am păstrat mesajul existent `CXCHECKFIFO / RESULT` și ID-ul tabelului `1792055730066`, folosite de configurația anterioară.[^23_1]

Am verificat sintaxa și am testat calculul soldurilor finale, agregarea pe preț, prețurile lipsă pe una dintre părți și totalurile. Integrarea MBO/Jython trebuie confirmată în instanța ta.

<div align="center">⁂</div>

[^23_1]: paste.txt


---

# ce parere ai despre asta - atunci cand soldul >=0

1.si pretul unitar este corect FIFO sa nu mai pui badfifo=U
2.sa recalculezi auditul pt urmatoarele tranzactii conform sold>=0
3\. tranzactiile de tip intrare din CXSTOCURI NU ar trebui sa fie verificate dpdv FIFO deci nu ar trebui sa primeasca flag bad fifo. ar trebui sa afiseze doar locatia SURSA de unde au venit.

in poza de mai sus am highlightat 2 tranzactii dupa care pretul NU ar fi trebuit sa afisezi badfifo=U sau =Y.
cum propui implementarea in scriptul de audit?

Sunt de acord cu direcția, dar aș introduce o regulă esențială: **reluarea** auditului trebuie să se facă dintr-o bază locală reconstruibilă, nu doar fiindcă un rând afișează `CXCURBAL >= 0`.

Aș implementa separat: verdictul de preț FIFO, verificarea soldului și afișarea intrărilor.

## 1. Preț FIFO corect: nu mai folosim U pentru o problemă separată de sold

În versiunea 5.1, o diferență de sold poate transforma rezultatul în `U`, chiar dacă prețul FIFO a fost calculat și este corect. Propun să schimbăm această regulă:


| Situație pentru o ieșire | Verdict propus |
| :-- | :-- |
| Cantitatea este acoperită de straturi cunoscute, iar prețul este corect | `BADFIFO=N` |
| Cantitatea este acoperită, dar prețul diferă | `BADFIFO=Y` |
| Nu putem determina alocarea/prețul pentru întreaga cantitate | `BADFIFO=U` |
| Există numai o diferență de `CXCURBAL` | Avertizare de sold separată, fără schimbarea verdictului de preț |

Exemplu:

```text
OK: FIFO asteptat 9,410 | Sursa=... | BADFIFO=N
```

Dacă soldul înregistrat nu corespunde calculului:

```text
OK: FIFO asteptat 9,410 | ATENTIE SOLD: inregistrat 8,000; calculat 10,000 | BADFIFO=N
```

Astfel, `BADFIFO` descrie prețul/alocarea FIFO, nu toate problemele jurnalului.

Totuși, `sold >= 0` nu este suficient ca să declarăm prețul corect: trebuie să existe și straturile anterioare necesare calculului.

## 2. Nu mai propagăm permanent blocarea după o insuficiență de stoc

Aici este modificarea principală de algoritm.

În locul unei variabile globale `blocked`, care poate opri toate mișcările următoare, propun două categorii:

- probleme recuperabile de disponibil: insuficiență de stoc sau început de istoric incomplet;
- probleme structurale: dată lipsă, ordine ambiguă, retur/anulare fără alocare demonstrabilă.

Pentru prima categorie, auditul continuă să urmărească intrările și poate relua verificarea ieșirilor viitoare. Pentru a doua, un sold pozitiv nu rezolvă automat ambiguitatea.

### Exemplul din captura anterioară

După epuizarea celor `33` de unități, apare o ieșire care duce soldul la `-19`. Ulterior, recepția de `+20` aduce soldul la `1`.[^25_1]

Propun următorul tratament:

```text
Ieșirea care produce deficitul:
    rămâne U, deoarece nu avea disponibil anterior suficient.

Recepția ulterioară:
    acoperă deficitul de 19;
    lasă 1 unitate disponibilă pentru auditul viitor.

Următoarea ieșire de 1:
    poate fi verificată normal;
    dacă prețul corespunde, primește N.
```

Recepția nu repară retroactiv ieșirea veche, dar nici nu trebuie ignorată pentru toate ieșirile viitoare.

### Atenție la mai multe prețuri

`CXCURBAL` este urmărit pe preț în logica jurnalului. Un sold zero sau pozitiv la `9,410` nu spune automat ce disponibil există la `8,520`.

De aceea, nu voi reseta toate straturile la fiecare rând cu sold pozitiv. Voi păstra straturile cunoscute și voi relua calculul numai pentru disponibilul care poate fi explicat prin jurnal. Dacă istoricul nu permite stabilirea ordinii straturilor, rămâne `U`, nu un `N` presupus.

## 3. Intrările obișnuite: fără BADFIFO în text

Sunt de acord: pentru intrările obișnuite acceptate în model, nu verificăm dacă „prețul intrării este FIFO”. Ele definesc straturile din care verificăm ieșirile.

Pentru `SHIPRECEIPT`, `RECEIPT` și partea pozitivă de `TRANSFER`, propun:

```text
FROMSTORELOC=C0220302
```

Fără:

```text
BADFIFO=N
BADFIFO=Y
BADFIFO=U
```

Intrările vor participa în continuare la reconstrucția disponibilului, dar nu vor fi numărate în sumar drept ieșiri FIFO corecte sau greșite.

Nu aș aplica însă automat această regulă tuturor cantităților pozitive. `RETURN` și `SHIPCANCEL` pot trebui să restaureze alocări istorice, nu să creeze straturi noi ca o recepție obișnuită.

## 4. De unde luăm locația-sursă

Există o limită practică: în datele citite acum din `CXSTOCURI`, locația-sursă nu este disponibilă ca atribut dedicat; versiunea veche o obținea din `MATRECTRANS.FROMSTORELOC`.[^25_2]

Propun o citire informativă minimă:

```text
CXSTOCURI.CXREFMBO = MATRECTRANS
CXSTOCURI.CXREFID  → MATRECTRANSID
                  → FROMSTORELOC
```

Această citire:

- servește exclusiv afișării provenienței;
- nu validează cantitatea, prețul, data sau expedierea-părinte;
- nu influențează calculul FIFO;
- nu blochează auditul dacă sursa lipsește.

Dacă locația nu poate fi obținută, afișăm:

```text
FROMSTORELOC=NEIDENTIFICAT
```

Nu folosim `CXSTOCURI.LOCATION`, deoarece aceea este gestiunea rândului auditat, nu neapărat originea intrării. Pentru o recepție de la furnizor, este posibil să nu existe deloc o magazie-sursă.

## 5. Modificările concrete în script

| Componentă | Modificare propusă |
| :-- | :-- |
| `audit_rows()` | Continuă după insuficiențe recuperabile și gestionează explicit disponibilul/deficitul |
| `flag()` | Stabilește verdictul FIFO numai pentru ieșiri, independent de avertizarea de sold |
| `description_visible()` | Intrările afișează doar proveniența; ieșirile afișează verdictul FIFO și eventual avertizarea de sold |
| Sumar | Numără separat ieșiri `N/Y/U`, intrări informative și probleme de sold |
| Proveniență | Citire minimă din `MATRECTRANS`, fără reintroducerea auditului între gestiuni |
| Reconciliere finală | Rămâne comparația informativă cu `INVLIFOFIFOCOST`, fără impact asupra `BADFIFO` |

Mai trebuie verificată și condiția de colorare din Application Designer: dacă aceasta marchează implicit orice rând fără `BADFIFO=N`, eliminarea indicatorului de pe intrări poate să nu elimine culoarea. Condiția trebuie să vizeze explicit ieșirile cu `BADFIFO=Y` sau `BADFIFO=U`.

Aceasta este implementarea pe care o recomand: nu mascăm erorile vechi, dar nici nu lăsăm o insuficiență veche să invalideze permanent tranzacțiile viitoare care au din nou o bază verificabilă.

<span style="display:none">[^25_3][^25_4]</span>

<div align="center">⁂</div>

[^25_1]: image.jpg

[^25_2]: paste.txt

[^25_3]: image.jpg

[^25_4]: https://www.perplexity.ai/search/0c2b20d4-9887-4d31-930f-0dd2b6a7d660


---

# nu m-am facut eu clar: la sold >= 0 este suficient ca să declansam verificarea fifo, asta nu garanteaza ca badfifo=N.

in plus, nu uita ca pt IESIRI vreau in Info Fifo sa afisezi si refid-ul INTRARII aferente pretului.

da, sunt de acord cu propunerea ta ''De unde luăm locația-sursă''
mai sunt si alte lucruri pe care tre sa le clarific inainte sa treci la modificarea scriptului?

Acum este clar: `CXCURBAL >= 0` este un **declanșator** pentru reluarea verificării FIFO, nu o condiție care stabilește automat `BADFIFO=N`.

## Regulile pe care le voi implementa

### 1. Reluarea auditului

Când soldul revine la `>= 0`, scriptul reia verificarea, fără să păstreze blocarea produsă de o insuficiență veche.

Rezultatul verificării poate fi:

- `N` — prețul ieșirii corespunde alocării FIFO calculate;
- `Y` — alocarea poate fi calculată, dar prețul ieșirii diferă;
- `U` — verificarea a fost declanșată, însă lipsesc informații suficiente pentru calculul întregii alocări.

Istoricul anterior nu este corectat retroactiv.

### 2. RefID-ul intrării pe fiecare ieșire

În „Info FIFO” păstrăm `Sursa` ca `CXREFID` al intrării consumate în simulare, nu `CXSTOCURIID`.

Pentru un singur strat:

```text
OK: FIFO asteptat 9,410 | Sursa=1337464898 | BADFIFO=N
```

Pentru mai multe straturi:

```text
DIFERENTA: pret 9,410; asteptat 8,965 | Sursa=1337464898,1337462764 | BADFIFO=Y
```

Sursele afișate vor fi cele ale alocării FIFO așteptate, inclusiv când prețul înregistrat pe ieșire este greșit. Nu voi căuta pur și simplu o intrare care are același preț cu ieșirea.

Dacă sursa este un `INITIAL` fără `CXREFID`, voi afișa explicit:

```text
Sursa=INITIAL
```

Nu voi inventa un RefID și nu voi reveni la afișarea `CXSTOCURIID`.

### 3. Intrările și proveniența

Intrările obișnuite nu vor avea `BADFIFO` în text. Vor afișa:

```text
FROMSTORELOC=C0220302
```

Locația va fi citită informativ din `MATRECTRANS`, fără validarea sau propagarea FIFO între gestiuni. Dacă nu poate fi identificată:

```text
FROMSTORELOC=NEIDENTIFICAT
```


### 4. Restul comportamentului

- Avertizarea de sold rămâne separată de verdictul privind prețul FIFO.
- Comparația finală cu `INVLIFOFIFOCOST` rămâne informativă.
- Auditul nu modifică date, cantități, prețuri sau solduri.
- Retururile și anulările nu sunt transformate automat în intrări/ieșiri obișnuite.


## Un singur punct mai trebuie stabilit

Când soldul revine la `>= 0` chiar pe un rând de ieșire, propun să verificăm FIFO începând cu acea ieșire, nu abia cu următoarea.

Exemplu:

```text
ISSUE -3, CXCURBAL=2
```

Scriptul încearcă verificarea chiar pentru acest `ISSUE -3`. Soldul pozitiv declanșează calculul, dar nu stabilește singur nici prețul așteptat, nici sursele.

Confirmi reluarea inclusiv pe rândul de ieșire care are `CXCURBAL >= 0`?

---

# da, confirm reluarea inclusiv pe rândul de ieșire care are CXCURBAL >= 0

Am implementat regula confirmată și am atașat scriptul **complet** `CXINVAUDIT`, versiunea `5.2-LOCAL-RECOVERY`.

## Ce face această versiune

### 1. Reia verificarea inclusiv pe ieșirea cu sold ≥ 0

O insuficiență veche nu mai blochează permanent auditul.

Când o ieșire are `CXCURBAL >= 0`, scriptul încearcă verificarea chiar pentru acel rând:

- `N` dacă alocarea poate fi calculată și prețul este corect;
- `Y` dacă alocarea poate fi calculată, dar prețul diferă;
- `U` dacă intrările identificabile nu acoperă întreaga ieșire.

Soldul pozitiv declanșează verificarea; nu creează automat stoc și nu garantează rezultatul.

Exemplu de rezultat:

```text
OK: FIFO LOCAL asteptat 9,410; baza locala din intrari;
audit reluat pe aceasta iesire | Sursa=1337394167 | BADFIFO=N
```


### 2. Păstrează RefID-urile intrărilor pe ieșiri

`Sursa` indică intrarea sau intrările consumate în alocarea FIFO așteptată:

```text
Sursa=1337464898
```

sau:

```text
Sursa=1337464898,1337462764
```

Pentru un strat `INITIAL` fără RefID:

```text
Sursa=INITIAL
```


### 3. Intrările afișează numai proveniența

Intrările obișnuite nu mai au `BADFIFO` în „Info FIFO”:

```text
FROMSTORELOC=C0220302
```

Locația este citită informativ din `MATRECTRANS`. Dacă nu poate fi identificată:

```text
FROMSTORELOC=NEIDENTIFICAT
```

Această citire nu validează sursa și nu influențează calculul FIFO.

### 4. Separă avertizarea de sold de verdictul de preț

Dacă prețul poate fi verificat, o diferență de sold nu îl mai transformă automat în `U`:

```text
OK: FIFO LOCAL asteptat 9,410;
ATENTIE SOLD: inregistrat 8,000; calculat 10,000 | Sursa=INITIAL | BADFIFO=N
```


### 5. Păstrează reconcilierea finală

Mesajul final include în continuare comparația informativă cu `INVLIFOFIFOCOST`, pe preț și pe totaluri de cantitate/valoare. Aceasta nu modifică `BADFIFO`.

## Instalare

1. Păstrează o copie a versiunii curente.
2. În Automation Scripts, deschide `CXINVAUDIT`.
3. Înlocuiește integral codul cu fișierul atașat.
4. Salvează și rulează `Check FIFO`.

Nu modifica launch point-ul sau butonul. Am păstrat mesajul `CXCHECKFIFO / RESULT` și ID-ul tabelului `1792055730066` din configurația existentă.[^27_1]

Scriptul scrie numai `DESCRIPTION_LONGDESCRIPTION`. Nu modifică date, cantități, prețuri sau solduri.

## Verificări efectuate

Am verificat sintaxa și am testat algoritmic:

- recuperarea după deficit și reluarea pe aceeași ieșire;
- rezultat `Y` după reluare, când prețul este greșit;
- păstrarea lui `U` când nu există suficiente intrări identificabile;
- afișarea surselor pentru mai multe straturi;
- intrările fără `BADFIFO`;
- avertizările de sold fără suprascrierea verdictului FIFO;
- regenerarea textelor la rerulare.

Retururile, anulările și ambiguitățile structurale rămân limite explicite: un sold pozitiv nu le rezolvă automat. Execuția MBO/Jython a noii versiuni trebuie confirmată în instanța ta.

<div align="center">⁂</div>

[^27_1]: paste.txt


---

# am evidentiat 3 perechi de matrectrans in pic1, iti poti da seama de imbunatatirea pe care ar trebui sa o facem pt flag-ul BADFIFO in aceste cazuri?

HINT: userul a gresit si cel putin data iesirii nu e corecta

Da — în cele trei perechi apare același tipar: ieșirea este datată înaintea recepției care ar putea să o acopere, dar recepția are un `MATRECTRANSID` mai mic decât ieșirea. Asta sugerează o problemă de **cronologie**, nu neapărat un preț FIFO greșit.[^28_1]

## 1. Ce observ în cele trei perechi

| Ieșire | Recepție ulterioară în jurnal | Indiciu |
| :-- | :-- | :-- |
| `1337395440`: 01.03.2026, `-19` la `9,410` | `1337394167`: 11.03.2026, `+20` la `9,410` | Recepția are ID mai mic; după ea soldul revine la `1` |
| `1337408057`: 01.04.2026, `-12` la `9,410` | `1337403898`: 03.04.2026, `+20` la `9,410` | Recepția are ID mai mic; după ea soldul revine la `8` |
| `1337476304`: 01.08.2026, `-24` la `8,520` | `1337475244`: 07.08.2026, `+40` la `8,520` | Recepția are ID mai mic; după ea soldul revine la `16` |

În fiecare caz, cantitatea recepționată acoperă deficitul, iar prețul este compatibil cu cel al ieșirii.[^28_1]

Totuși, ID-ul mai mic este un indiciu de investigat, nu o dovadă suficientă a datei reale. Nu aș înlocui automat ordinea după `CXDOCUMENTDATE` cu ordinea după ID.

## 2. Îmbunătățirea pe care o propun

În loc de mesajul generic:

```text
NEVERIFICAT: Stoc anterior insuficient;
se asteapta o baza locala recuperabila | BADFIFO=U
```

scriptul ar trebui să distingă:

1. stoc insuficient fără o explicație identificată;
2. stoc insuficient cu o posibilă inversare de date identificată.

Pentru prima pereche, de exemplu:

```text
DATA SUSPECTA: iesire anterioara unei receptii candidate;
deficit 19,000; receptie 1337394167 din 11.03.2026;
cantitate 20,000 la 9,410; pret compatibil |
SursaCandidata=1337394167 | BADFIFO=U | MOTIV=ORDINE_DATE
```

Aș păstra `SursaCandidata`, nu `Sursa`, deoarece încă nu am demonstrat că acea intrare era disponibilă la data înregistrată a ieșirii.

## 3. Cum ar identifica scriptul aceste situații

La o ieșire cu disponibil anterior insuficient:

1. Calculează deficitul neacoperit.
2. Caută în tranzacțiile ulterioare din aceeași gestiune intrări candidate.
3. Verifică articolul, grupa relevantă, cantitatea și prețul.
4. Folosește `CXREFID` mai mic drept indiciu suplimentar numai când referințele provin din același obiect — aici, `MATRECTRANS`.
5. Dacă identifică un candidat credibil, afișează motivul `ORDINE_DATE` și RefID-ul candidatului.

Dacă există mai multe recepții posibile sau prețuri diferite, mesajul trebuie să spună că asocierea este ambiguă, nu să aleagă arbitrar.

## 4. Ce facem cu BADFIFO

Nu aș transforma direct aceste ieșiri în `BADFIFO=N`, deoarece, la datele existente, ele tot nu au stoc anterior suficient.

Aș folosi:


| Situație | Rezultat |
| :-- | :-- |
| Alocare FIFO demonstrată și preț corect | `BADFIFO=N` |
| Alocare demonstrată și preț greșit | `BADFIFO=Y` |
| Insuficiență cu posibilă dată greșită | `BADFIFO=U`, cu `MOTIV=ORDINE_DATE` |
| Insuficiență fără candidat | `BADFIFO=U`, cu `MOTIV=STOC_INSUFICIENT` |

Astfel, utilizatorul vede imediat că trebuie investigată data, nu că trebuie schimbat prețul.

Putem diferenția și culoarea în interfață: de exemplu, portocaliu pentru `ORDINE_DATE`, galben pentru diferență de preț.

## 5. După confirmarea și corectarea datei

După mutarea ieșirii la data reală corectă și rularea din nou a auditului, scriptul verifică alocarea normal. Dacă prețul este corect, rezultatul devine `N`, iar recepția verificată apare în `Sursa`.

Important: butonul actual `CXUPDFIFOROW` mută tranzacția după maximul aceleiași zile. Nu rezolvă aceste exemple, unde trebuie analizată o mutare între zile diferite. Pentru asta este necesară o acțiune distinctă, cu data propusă afișată și confirmată înainte de salvare.

Așadar, îmbunătățirea este să recunoaștem „ieșire posibil antedatată” ca motiv distinct de audit, să indicăm recepția candidată și să evităm o corecție inutilă de preț. Nu folosim însă o recepție viitoare ca și cum ar fi fost deja disponibilă, înainte de confirmarea datei.

<div align="center">⁂</div>

[^28_1]: image.jpg


---

# as vrea ca daca pt o iesire gasim un refid din acelasi obiect mai mic decat cel al iesirii atunci sa punem BADFIFO=N, cu MOTIV=ORDINE_DATE

da-mi scriptul end 2 end

Am implementat regula și am atașat scriptul **complet** `CXINVAUDIT`, versiunea `5.3-LOCAL-ORDINE-DATE`.

## Regula nouă

Pentru o ieșire rămasă fără stoc anterior suficient, scriptul caută intrări ulterioare în același jurnal care:

- au același `CXREFMBO` ca ieșirea;
- au `CXREFID` mai mic decât RefID-ul ieșirii;
- au preț compatibil cu prețul ieșirii;
- acoperă deficitul prin cantități care nu au fost deja rezervate pentru altă excepție.

Dacă sunt îndeplinite condițiile, afișează:

```text
OK: pret compatibil 9,410; intrare ulterioara cu RefID anterior;
data iesirii de verificat (conventie) |
Sursa=1337394167 | MOTIV=ORDINE_DATE | BADFIFO=N
```

Acest `N` este convenția solicitată de tine pentru situația de ordine a datelor. Nu înseamnă că scriptul a confirmat sau a corectat data reală.

## Rezultatul pentru cele trei perechi

Am testat algoritmul pe secvența din captura ta. Cele trei ieșiri primesc rezultatul următor:[^29_1]


| RefID ieșire | RefID intrare identificată | Rezultat |
| :-- | :-- | :-- |
| `1337395440` | `1337394167` | `BADFIFO=N`, `MOTIV=ORDINE_DATE` |
| `1337408057` | `1337403898` | `BADFIFO=N`, `MOTIV=ORDINE_DATE` |
| `1337476304` | `1337475244` | `BADFIFO=N`, `MOTIV=ORDINE_DATE` |

Nu este suficient să existe orice intrare veche cu ID mai mic: o intrare deja anterioară și epuizată nu justifică această excepție.

O diferență FIFO deja demonstrată, marcată `Y`, nu este suprascrisă de regula nouă.

## Ce am păstrat

- Reluarea verificării inclusiv pe ieșirea cu `CXCURBAL >= 0`.
- RefID-urile intrărilor în `Sursa`.
- Intrările afișate numai cu `FROMSTORELOC`, fără `BADFIFO`.
- Avertizările de sold separate de verdictul de preț.
- Reconcilierea informativă finală cu `INVLIFOFIFOCOST`.
- Protejarea notelor manuale și verificarea modificărilor concurente.

Sumarul final numără separat excepțiile:

```text
Din N, conventie ORDINE_DATE=3.
```

Regula schimbă numai verdictul și textul auditului. Nu mută tranzacțiile și nu scade încă o dată cantitățile candidate din replay-ul cronologic.

## Instalare

1. Păstrează o copie a versiunii curente.
2. Deschide Automation Scripts → `CXINVAUDIT`.
3. Înlocuiește integral codul cu fișierul atașat.
4. Salvează și rulează `Check FIFO`.

Butonul, launch point-ul și mesajul `CXCHECKFIFO / RESULT` rămân neschimbate.

Am verificat sintaxa și am testat cele trei perechi, prețurile incompatibile, obiectele diferite, cantitățile insuficiente și prevenirea reutilizării cantităților între excepții. Execuția noii versiuni în Maximo/Jython trebuie confirmată în instanța ta.

<div align="center">⁂</div>

[^29_1]: image.jpg


---

# primesc eroarea asta. in plus

as vrea sa eliminam din script si chestiile fixe folosite pt dry run

Da. Eroarea provine din folosirea `re.match()` în funcția care recunoaște textele generate anterior. În contextul tău Jython, obiectul rezolvat sub numele `re` nu expune metoda `match`. Nu este o eroare de calcul FIFO sau de lungime a scriptului.[^30_1]

Soluția este să eliminăm complet dependența de expresii regulate.

## 1. Înlocuiește funcția afectată

În `CXINVAUDIT`, caută:

```python
def generated_compact_info(value):
```

Înlocuiește întreaga funcție, până înaintea următorului `def`, cu varianta de mai jos. Nu modifica funcția separată `generated_compact_legacy()`.

```python
def generated_compact_info(value):
    value = info_plaintext(value)
    if "\n" in value:
        return False

    if value.startswith("FROMSTORELOC=") and " | " not in value:
        return bool(value[len("FROMSTORELOC="):].strip())

    prefix = "INITIAL: FIFO LOCAL "
    if value.startswith(prefix):
        parts = value[len(prefix):].split(" buc. la ")
        if len(parts) != 2:
            return False

        for part in parts:
            if part == "necunoscut":
                continue
            try:
                number = dec(part.replace(",", "."))
                if number is None or fmt_ro(number) != part:
                    return False
            except Exception:
                return False
        return True

    if value == "INITIAL: BAZA NECONCLUDENTA; vezi rezumatul auditului":
        return True

    parts = value.split(" | ")
    if "MOTIV=ORDINE_DATE" in parts:
        if parts.count("MOTIV=ORDINE_DATE") != 1:
            return False
        parts.remove("MOTIV=ORDINE_DATE")
        value = " | ".join(parts)

    return generated_compact_legacy(value)
```

Am atașat și fragmentul într-un fișier text. Este o **corecție** pentru scriptul existent, nu un script autonom.

Poți actualiza și identificatorul versiunii:

```python
VERSION = "5.3.1-LOCAL-ORDINE-DATE"
```


## 2. Despre elementele fixe pentru dry-run

În versiunea 5.3 livrată nu mai există restricții de pilot:

- nu există `DRY_RUN`;
- nu există `PILOT_SCOPE`;
- nu există articol/site/gestiune de test impuse;
- nu există RefID-uri de test impuse;
- nu există o dată fixă pentru selecția tranzacțiilor.

Articolul, site-ul și gestiunea sunt preluate din înregistrarea Inventory selectată.

Aș păstra următoarele constante, deoarece nu sunt elemente de dry-run:


| Constantă | Rol |
| :-- | :-- |
| `FIFO_TABLE_ID` | Identifică tabelul pentru refresh |
| `MAX_ROWS` | Protecție împotriva încărcării unui volum excesiv |
| `MAX_DESCRIPTION` | Protecție la generarea textului |
| `MAX_RECON_LINES` | Limitează lungimea comparației din popup; restul se scrie în log |
| `COST_TOLERANCE`, `QTY_TOLERANCE` | Toleranțe pentru comparațiile numerice |
| `FIX_PREFIX` | Recunoaște și protejează istoricul corecțiilor anterioare |

Nu le-aș elimina împreună cu restricțiile de test.

## 3. După modificare

Salvează scriptul și rulează din nou `Check FIFO`. Regula:

```text
BADFIFO=N | MOTIV=ORDINE_DATE
```

rămâne neschimbată.

Am verificat sintaxa funcției și am testat recunoașterea formatelor `INITIAL`, `FROMSTORELOC`, `Sursa=INITIAL` și `MOTIV=ORDINE_DATE`, inclusiv refuzul textelor cu note manuale adăugate. Compilarea și rularea în instanța ta Jython trebuie confirmate după înlocuire.

<div align="center">⁂</div>

[^30_1]: image.jpg


---

# da-mi scriptul cap coada

Am atașat scriptul **complet**, `CXINVAUDIT 5.3.1-LOCAL-ORDINE-DATE`, cu 828 de linii. Înlocuiește integral conținutul scriptului existent — nu mai trebuie aplicat separat fragmentul din mesajul anterior.

## Ce conține

- Corecția pentru eroarea `re.match`: nu mai folosește expresii regulate, eliminând dependența care a eșuat în captura ta.[^31_1]
- Fără `DRY_RUN`, `PILOT_SCOPE`, articol, gestiune, dată sau RefID de test impuse.
- Reluarea verificării inclusiv pe ieșirea cu `CXCURBAL >= 0`.
- Regula convenită `BADFIFO=N | MOTIV=ORDINE_DATE`, când intrările ulterioare eligibile au RefID mai mic, același obiect, preț compatibil și cantitate suficientă.
- RefID-urile intrărilor în `Sursa`.
- Intrări afișate numai cu `FROMSTORELOC`, fără `BADFIFO`.
- Comparația informativă finală cu `INVLIFOFIFOCOST`, pe preț și pe totaluri de cantitate/valoare.

Regula `ORDINE_DATE` modifică numai verdictul și explicația auditului; nu corectează efectiv datele tranzacțiilor.

## Instalare

1. Păstrează o copie a versiunii curente.
2. Deschide Automation Scripts → `CXINVAUDIT`.
3. Înlocuiește tot codul cu fișierul atașat.
4. Salvează și rulează `Check FIFO`.

Butonul și launch point-ul rămân neschimbate. Am păstrat mesajul `CXCHECKFIFO / RESULT`, ID-ul tabelului de refresh și limitele de siguranță.

Am verificat sintaxa și am retestat cele trei perechi evidențiate, regenerarea textelor la rerulare, rezervarea cantităților candidate și protejarea notelor manuale. Scriptul scrie exclusiv `DESCRIPTION_LONGDESCRIPTION`; nu modifică date, cantități, prețuri sau solduri. Execuția în Maximo/Jython trebuie confirmată în instanța ta.

<div align="center">⁂</div>

[^31_1]: image.jpg


---

# exista bgpink? vreau sa colorez conditionat cand data este suspecta...

`bgpink` nu apare în lista uzuală de clase de fundal Maximo, deci nu m-aș baza pe ea ca fiind standard. Va funcționa numai dacă este definită în CSS-ul temei active din instalarea ta. Clasele documentate includ `bgred`, `bgorange`, `bgyellow`, `bgpurple`, `bggray` etc.[^32_1]

## Varianta rapidă: portocaliu pentru data suspectă

În configurația din captură, folosește:


| Proprietate | Valoare |
| :-- | :-- |
| `cssclass` | `bgorange` |

Aplicarea condiționată a unei clase prin proprietatea `cssclass` este mecanismul folosit pentru colorarea câmpurilor în Application Designer.[^32_2]

Condiția trebuie să urmărească markerul:

```text
MOTIV=ORDINE_DATE
```

Nu `BADFIFO=U` sau `BADFIFO=Y`, deoarece pentru aceste cazuri am convenit:

```text
MOTIV=ORDINE_DATE | BADFIFO=N
```

Aș aplica această culoare pe coloana **Data**, pentru a diferenția problema de cronologie de o diferență de preț.

## Dacă vrei neapărat roz

Trebuie adăugată o clasă CSS personalizată în resursele temei, de exemplu:

```css
.cxdatesuspect {
    background-color: #ffd6e7 !important;
    color: #161616 !important;
}
```

Apoi, în Conditional Properties:

```text
Proprietate: cssclass
Valoare:     cxdatesuspect
```

Fără punct înaintea numelui în câmpul „Valoare”. Clasa trebuie distribuită prin mecanismul de customizare al deploymentului și verificată pe controlul și tema folosite; simpla introducere a numelui în Application Designer nu creează stilul.[^32_3][^32_1]

Pentru moment, recomand `bgorange`: este o clasă cunoscută și separă vizual data suspectă de galbenul folosit deja pentru diferențele FIFO.

<span style="display:none">[^32_10][^32_11][^32_12][^32_13][^32_14][^32_15][^32_16][^32_4][^32_5][^32_6][^32_7][^32_8][^32_9]</span>

<div align="center">⁂</div>

[^32_1]: https://bportaluri.com/blog/2021/04/highlight-table-rows-conditionally/

[^32_2]: https://bportaluri.com/blog/2012/03/change-color-field-conditional/

[^32_3]: https://www.prometheusgroup.com/resources/posts/color-yourself-happy-changing-the-colors-of-specific-fields-in-ibm-maximo

[^32_4]: image.jpg

[^32_5]: https://www.ibm.com/support/pages/conditionally-adding-field-background-colors

[^32_6]: https://www.ibm.com/support/pages/apar/IJ04205

[^32_7]: https://www.amazon.com/-/es/Conjunto-bufanda-invierno-calentadora-pantalla/dp/B07ZSDTCF3

[^32_8]: https://www.magazineluiza.com.br/busca/bolsa+envelope+grande+feminina/

[^32_9]: https://davix.ai/en/docs/facturacion/modulos/documentos-ventas/

[^32_10]: https://moremaximo.com/discussion/mas-91-carbon-and-cssclass-important-not-respecting-custom-ctrl-textboxsize-value-set-in-application-designer

[^32_11]: https://moremaximo.com/question/colour-coding-checkbox-background

[^32_12]: https://community.ibm.com/community/user/viewdocument/stylize-a-label-or-text-control-to?CommunityKey=3d7261ae-48f7-481d-b675-a40eb407e0fd\&tab=librarydocuments

[^32_13]: https://davix.ai/en/docs/facturacion/modulos/documentos-ventas-salud/

[^32_14]: https://stackoverflow.com/questions/34547691/change-the-color-of-a-field-in-maximo

[^32_15]: https://www.vasco-nails.es/es/bases-y-tops/1365-base-building-gummy-pink-15ml.html

[^32_16]: https://guatemala.yaxa.co/products/dihklcio-bolso-de-noche-bolso-sobre-clutch-cadena-para-mujer-bolso-de-hombro-munequera-bolso-de-mano-negro


---

# ok, acum ca am terminat partea de verificare FIFO....hai sa revenim la implementarea pentru butonul nr 2 pentru corectia tranzactiilor de IESIRE (fara cele de INTRARE) cu FIFO (si poate si split quantity) gresite

Da. Reluăm implementarea pentru **corecția ieșirilor**, cu buton separat pe fiecare rând din `CXSTOCURI`. `CXINVAUDIT` rămâne pentru verificare, iar `CXUPDFIFOROW` rămâne pentru modificarea datei.

Important: `CXFIFOFIXISSUE` livrat anterior este doar versiunea de analiză. Partea de salvare trebuie completată, nu activată prin schimbarea unui flag.

## 1. Comportamentul butonului nr. 2

Fluxul rămâne cel stabilit:

```text
Apeși pe o ieșire
    ↓
Identifică operațiunea și spliturile ei
    ↓
Recalculează alocarea FIFO
    ↓
Corectează numai operațiunea selectată
    ↓
Rulezi Check FIFO și verifici
    ↓
Alegi următoarea ieșire
```

Butonul nu va procesa automat toate liniile galbene.

### Reguli de eligibilitate

- Se aplică numai pe rânduri cu `CXQTY < 0`.
- Nu modifică prețurile, cantitățile sau datele recepțiilor.
- Recalculează alocarea înainte de salvare; nu folosește textul „Info FIFO” drept singura autoritate.
- Refuză corecția de preț dacă rezultatul este `MOTIV=ORDINE_DATE`: acolo problema de dată trebuie rezolvată separat.
- Refuză operațiunile a căror cantitate totală sau proveniență nu poate fi demonstrată.


## 2. Separăm ISSUE de ieșirile prin transfer

Nu aș folosi același handler de salvare pentru toate tipurile de ieșire.


| Tip | Tratament propus |
| :-- | :-- |
| `ISSUE / MATUSETRANS` | Primul handler: corecție de consum, inclusiv redistribuirea spliturilor |
| `SHIPTRANSFER / MATRECTRANS` | Handler distinct, cu verificarea recepțiilor/anulărilor asociate |
| Partea negativă a unui `TRANSFER` | Handler distinct, deoarece există și partea de intrare |
| Retururi/anulări | Refuzate în prima versiune |

Pentru transferuri, schimbarea numai a ieșirii poate lăsa prețuri sau cantități neconforme cu intrarea asociată. Cum ai cerut să nu corectăm intrările, nu vom modifica automat asemenea operațiuni dacă asta ar rupe coerența perechii.

Prin urmare, prima versiune de salvare o construim pentru `ISSUE / MATUSETRANS`, inclusiv cazul `209409 + 209410`.

## 3. Corecția spliturilor pentru consum

Gruparea se face după:

```text
INVUSEID + INVUSELINEID
```

cu verificări suplimentare pe articol, item set, site, gestiune, destinație și dimensiunile relevante ale stocului.

Nu impunem `TRANSDATE` identic la nivel de milisecundă și nu grupăm doar fiindcă ID-urile sunt consecutive.

Pentru exemplul discutat:


| MATUSETRANSID | Cantitate actuală → corectă | Preț actual → corect |
| :-- | :-- | :-- |
| `209409` | -3 → -2 | 9,410 → 9,410 |
| `209410` | -1 → -2 | 9,410 → 8,520 |

Cantitatea totală rămâne `-4`. Valoarea consumului, în modul, devine `35,860`, în loc de `37,640`.

Această corecție trebuie să trateze și valorile financiare și proveniența, nu numai câmpurile `QUANTITY` și `UNITCOST`. IBM documentează că un consum FIFO poate genera mai multe tranzacții financiare, corespunzătoare costurilor utilizate din `INVLIFOFIFOCOST`.[^33_1]

## 4. Ce modificăm și ce păstrăm

### În operațiunea selectată

- cantitățile spliturilor;
- prețurile și valorile aplicabile;
- reprezentarea corespunzătoare în `CXSTOCURI`;
- legăturile de proveniență, dacă analiza confirmă că trebuie schimbate.


### În jurnalul ulterior

Recalculăm `CXCURBAL` pe partițiile de preț afectate. Asta poate include soldul afișat pe o recepție ulterioară, dar nu înseamnă modificarea cantității sau prețului recepției.

### Protecții

- cantitatea totală a liniei de consum rămâne neschimbată;
- prima versiune reutilizează spliturile numai dacă numărul existent corespunde celui necesar;
- nu creează și nu șterge arbitrar `MATUSETRANS`;
- nu reconsumă stocul oficial doar fiindcă a fost schimbată cantitatea unui rând;
- o nouă apăsare pe o operațiune deja corectă nu trebuie să producă o nouă corecție.


## 5. Datele necesare pentru finalizarea salvării

Mai lipsesc extrasele solicitate anterior. Acestea sunt necesare în special pentru `LINECOST`, celelalte valori și legăturile `MATRECTRANSID` diferite ale spliturilor. Semnul valorilor nu trebuie dedus simplu din semnul cantității; tranzacțiile de consum și retur au convenții financiare proprii.[^33_2]

Rulează și exportă rezultatele acestor interogări:

```sql
-- Toate tranzactiile aceleiasi linii de consum.
SELECT *
FROM MATUSETRANS
WHERE INVUSEID = 62256
  AND INVUSELINEID = 164724
ORDER BY ACTUALDATE, MATUSETRANSID;

-- Linia originala de consum.
SELECT *
FROM INVUSELINE
WHERE INVUSELINEID = 164724;

-- Legaturile existente si receptiile propuse de audit.
SELECT *
FROM MATRECTRANS
WHERE MATRECTRANSID IN (
    1337409157,
    1337430204,
    1337464898,
    1337462764
);

-- Starea actuala a straturilor oficiale.
SELECT *
FROM INVLIFOFIFOCOST
WHERE ITEMNUM = '230690001'
  AND SITEID = 'C02'
  AND LOCATION = 'C0220302MON'
ORDER BY COSTDATE, INVLIFOFIFOCOSTID;
```

Acestea ne permit să trecem de la planul teoretic `2 + 2` la un handler de salvare care corectează coerent operațiunea, fără să lase costurile, legăturile și straturile oficiale în dezacord. Trimite cele patru rezultate, ideal ca CSV sau XLSX.

<span style="display:none">[^33_10][^33_11][^33_12][^33_13][^33_14][^33_15][^33_16][^33_3][^33_4][^33_5][^33_6][^33_7][^33_8][^33_9]</span>

<div align="center">⁂</div>

[^33_1]: https://www.ibm.com/docs/en/mci/7.6.1?topic=application-issue-current-item-action

[^33_2]: https://www.ibm.com/support/pages/gl-account-functionality-and-matusetrans-table

[^33_3]: https://publibfp.dhe.ibm.com/epubs/pdf/3256343b.pdf

[^33_4]: https://public.dhe.ibm.com/systems/z/z_coursematerials/lscc/Large_Scale_Commercial_Computing_Student.pdf

[^33_5]: https://public.dhe.ibm.com/software/tivoli_support/maximo/Maximo4/411P08/MX411P08RN.pdf

[^33_6]: https://public.dhe.ibm.com/software/tivoli_support/maximo/Maximo5/52P09/MX52_P09.pdf

[^33_7]: https://www.ibm.com/docs/en/maximo-eam-saas?topic=application-return-previously-issued-item

[^33_8]: https://public.dhe.ibm.com/software/commerce/doc/ssfs/91/Product_Concepts_Guide.pdf

[^33_9]: https://www.ibm.com/support/pages/apar/IV51972

[^33_10]: https://www.ibm.com/docs/en/maximo-sap-con/8.1.0?topic=switches-values-collaboration

[^33_11]: https://community.ibm.com/community/user/discussion/checking-wo-cost-fields-vs-trans-tables

[^33_12]: projects.maximo.fifo_audit_rules

[^33_13]: https://www.ibm.com/support/pages/why-does-item-fifo-cost-cost-average-cost-time-its-consumption

[^33_14]: https://www.ibm.com/support/pages/difference-matusetrans-line-cost-versus-actual-cost

[^33_15]: https://www.ibm.com/docs/en/mci/7.6.2?topic=application-inventory-costing

[^33_16]: https://www.ibm.com/docs/en/order-management-sw/10.0.0?topic=ic-inventory-costing-method-2-first-in-first-out-fifo


---

# ref pic2 - ce cod de buton sa folosesc?

despre pic1 discutam in mesajul urmator...

Pentru câmpul „Pictograma evenimentului”, îți propun **`nav_icon_save.gif`** — pictograma de salvare, diferită de săgeata folosită pentru modificarea datei. Acest nume este utilizat în resursele UI Maximo.[^34_1]

## Configurația pentru butonul nr. 2

| Câmp | Valoare |
| :-- | :-- |
| Eveniment | `CXFIFOFIXISSUE` — păstrează valoarea actuală |
| Descrierea evenimentului | `Corecteaza consum FIFO - cantitate, pret si valoare` |
| Pictograma evenimentului | `nav_icon_save.gif` |
| ID țintă | Lasă gol, conform configurației butonului de linie |

În „Descrierea evenimentului”, înlocuiește textul:

```text
CXFIFO / FIXISSUERESULT / {0}
```

cu descrierea funcțională de mai sus. Grupul și cheia mesajului se configurează separat în Messages; nu trebuie puse în tooltip-ul butonului.

Astfel, cele două butoane vor fi distincte:

- `btn_next.gif` → modificare dată și recalculare solduri;
- `nav_icon_save.gif` → acțiunea pentru corectarea consumului FIFO.

Schimbarea pictogramei nu modifică funcționalitatea scriptului. Dacă `CXFIFOFIXISSUE` conține încă versiunea `PLAN-ONLY`, butonul va continua să facă doar analiza, nu salvarea.

<span style="display:none">[^34_10][^34_11][^34_12][^34_13][^34_14][^34_15][^34_16][^34_17][^34_2][^34_3][^34_4][^34_5][^34_6][^34_7][^34_8][^34_9]</span>

<div align="center">⁂</div>

[^34_1]: https://github.com/IBM/MaximoForgeViewerPlugin/blob/master/tools/maximo/en/bimlmv/V7606_07.dbc

[^34_2]: image.jpg

[^34_3]: image.jpg

[^34_4]: https://www.ibm.com/docs/en/masv-and-l/maximo-ref/cd?topic=components-adding-navigation-items

[^34_5]: https://www.ibm.com/docs/fr/masv-and-l/maximo-manage/cd?topic=process-workflow-tool-palette-buttons

[^34_6]: https://www.ibm.com/docs/ja/SSLKT6_7.6.1.2/com.ibm.mbs.doc/pdf_mbs_devapps.pdf?view=kc

[^34_7]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/webclient/system/beans/AppBean.html

[^34_8]: https://bportaluri.com/wp-content/downloads/MaximoAutomationScriptsQuickReference.pdf

[^34_9]: https://www.scribd.com/document/249228868/Mam71-App-Dev-Guide

[^34_10]: https://www.maximotimes.com/maximo/customize-report-toolbar-icons-in-maximo/

[^34_11]: https://community.ibm.com/community/user/viewdocument/conditionally-changing-user-interfa?CommunityKey=3d7261ae-48f7-481d-b675-a40eb407e0fd

[^34_12]: https://community.ibm.com/community/user/asset-facilities/discussion/application-designer-menu-icons

[^34_13]: https://relia.app/files/maximo-7-training-books/MED0148_Workflow_print.pdf

[^34_14]: https://public.dhe.ibm.com/software/tivoli_support/maximo/Maximo5/52P09/MX52_P09.pdf

[^34_15]: https://services.anu.edu.au/files/guidance/Maximo_Navigation.pdf

[^34_16]: https://www.scribd.com/document/71536347/Ad-01

[^34_17]: https://github.com/ibm-maximo-dev/maximo-scripting/blob/master/samples/sample05/pic2.png


---

# ok, acum as vrea sa intelegi ce nu e bine din pic1 de mai sus si apoi sa-mi spui care sunt select-urile pe care sa le rulez pe db astfel incat sa poti construi varianta finala a scriptului CXFIFOFIXISSUE.

Da. În pic1 se vede momentul în care consumurile trebuiau să treacă de la stratul `9,410` la stratul `8,520`, dar au continuat să fie înregistrate la `9,410`. Prima corecție trebuie făcută la nivelul **spliturilor** aceleiași operațiuni, nu prin înlocuirea fiecărui preț cu valoarea medie afișată de audit.[^35_1]

Am atașat un fișier SQL cu toate cele 13 extrase necesare. Conține numai `SELECT`, fără modificări de date.

## 1. Ce nu este bine în pic1

După ieșirea din `18.07.2026`, jurnalul arată:

- `2` unități rămase la `9,410`;
- `12` unități disponibile la `8,520`, din recepția `1337462764`.[^35_1]

Urmează cele două splituri ale consumului de `4` unități:

```text
209409: -3 la 9,410
209410: -1 la 9,410
```

Pentru acestea avem deja indiciul documentar relevant: același `INVUSEID=62256` și `INVUSELINEID=164724`.[^35_2]

Alocarea corectă este:

```text
209409: -2 la 9,410
209410: -2 la 8,520
```

Prețul `9,113` afișat de audit pe primul rând este media ponderată a alocării așteptate pentru acel rând de `3` unități. Nu este prețul la care trebuie rescris automat consumul logic de `4` unități.

## 2. Rezultatul așteptat pentru întreaga secvență galbenă

Sub rezerva confirmării grupurilor în datele-sursă, aceasta este distribuția urmărită:


| MATUSETRANSID | Cantitate actuală → propusă | Preț actual → propus | Sold rezultat în jurnal |
| :-- | :-- | :-- | --: |
| `209409` | -3 → -2 | 9,410 → 9,410 | 0 la 9,410 |
| `209410` | -1 → -2 | 9,410 → 8,520 | 10 la 8,520 |
| `209419` | -4 → -4 | 9,410 → 8,520 | 6 la 8,520 |
| `210144` | -3 → -3 | 9,410 → 8,520 | 3 la 8,520 |
| `210145` | -1 → -1 | 9,410 → 8,520 | 2 la 8,520 |
| `211307` | -2 → -2 | 9,410 → 8,520 | 0 la 8,520 |

Cele șase rânduri însumează `14` unități: `2` trebuie consumate la `9,410`, iar `12` la `8,520`.[^35_1]

Pe baza acestor prețuri, valorile în modul sunt:

```text
Înregistrat: 14 × 9,410                  = 131,740
FIFO:         2 × 9,410 + 12 × 8,520     = 121,060
Diferență:                                  10,680
```

Acestea sunt calcule din cantitate și PU; trebuie comparate cu `ACTUALCOST`, `LINECOST` și celelalte valori oficiale înainte de salvare.

După corectarea tuturor acestor operațiuni, recepțiile din august de `+28` și `+24` ar duce soldul la `52` la prețul `8,520`, nu la `64`, pentru că cele `12` unități din iulie ar fi fost consumate corect. Nu schimbăm cantitatea sau prețul recepțiilor, ci soldul lor ulterior din jurnal.

## 3. Select-urile din fișierul atașat

### Extrasele de date — secțiunile 01–10

| Secțiune | Obiect | Ce trebuie să aflăm |
| :-- | :-- | :-- |
| `01` | `CXSTOCURI` | Istoricul complet al articolului în gestiune, inclusiv tranzacțiile ulterioare |
| `02` | `MATUSETRANS` | Cele șase ieșiri și toate spliturile liniilor lor, inclusiv eventuale retururi |
| `03` | `INVUSELINE` | Cantitatea originală, destinația și dimensiunile liniei de consum |
| `04` | `INVUSE` | Documentele și starea lor |
| `05` | `MATRECTRANS` | Recepțiile relevante și legăturile existente ale spliturilor |
| `06` | `INVENTORY` | Configurația de cost și `ITEMSETID` real |
| `07` | `ITEM` | Rotating, condition-enabled și celelalte atribute relevante |
| `08` | `INVBALANCES` | Soldul fizic actual și dimensiunile stocului |
| `09` | `INVLIFOFIFOCOST` | Straturile oficiale actuale, cantitățile și proveniența lor |
| `10` | `WORKORDER` | Eventualele comenzi de lucru care primesc costurile consumurilor |

Secțiunea `02` nu citește doar cele șase ID-uri. Identifică liniile lor `INVUSEID + INVUSELINEID`, apoi extrage toate tranzacțiile asociate acelor linii. Astfel nu omitem un split suplimentar sau un retur.

Secțiunea `05` include atât recepțiile propuse de audit, cât și `MATRECTRANSID`-urile indicate deja de consumuri. Nu presupunem că aceste referințe au aceeași semnificație și nu le înlocuim automat.

### Configurația tehnică — secțiunile 11–13

| Secțiune | Obiect | De ce este necesar |
| :-- | :-- | :-- |
| `11` | `MAXATTRIBUTE` | Tipurile, lungimile și preciziile efective ale câmpurilor de cantitate/cost/valoare |
| `12` | `MAXRELATIONSHIP` | Relațiile disponibile pentru proveniență și salvare coordonată |
| `13` | `SCRIPTLAUNCHPOINT` | Automatizările locale care pot interveni la salvarea obiectelor afectate |

Dacă secțiunea `13` returnează launch point-uri relevante, următorul pas poate fi verificarea codului scripturilor respective. Lista singură ne arată unde există intervenții, nu ce efect au.

## 4. Cum să rulezi și să exporți

1. Folosește conexiunea cu schema Maximo curentă. Dacă schema nu este implicită, prefixează tabelele cu schema ta.
2. Rulează fiecare secțiune separat.
3. Exportă rezultatele în CSV sau XLSX, cu numărul secțiunii în denumire.
4. Păstrează toate coloanele, inclusiv `ROWSTAMP`, valorile nule și timestamp-urile complete.
5. Nu rotunji costurile sau valorile în export.
6. Comunică și rezultatele goale; sunt relevante.
7. Pe cât posibil, rulează extrasele fără corecții sau procese concurente care modifică acel articol.

Straturile din `INVLIFOFIFOCOST` sunt cele actuale. Nu le vom interpreta ca fiind automat stocul existent la `19.07.2026`; istoricul trebuie reconstruit separat.

ID-urile din SQL sunt doar filtre pentru diagnosticul acestui caz. Nu vor deveni restricții fixe în scriptul final.

## 5. Ce vom putea decide din aceste rezultate

Pe baza exporturilor putem definitiva:

- care rânduri aparțin aceleiași operațiuni;
- ce cantități și prețuri se redistribuie;
- ce valori și legături oficiale trebuie actualizate sau compensate;
- ce solduri de jurnal ulterioare se recalculează;
- cum reconciliem straturile oficiale fără consum dublu;
- ce efecte trebuie verificate asupra destinației costului.

Și păstrăm fluxul cerut: o apăsare corectează operațiunea selectată, inclusiv spliturile ei; verifici, apoi alegi altă linie. Celelalte consumuri din tabel nu vor fi corectate automat în aceeași apăsare.

<div align="center">⁂</div>

[^35_1]: image.jpg

[^35_2]: image.jpg


---

# atasez rezultatele. workorder nu a intors niciun rezultat; construieste scriptul de update fifo pe linie. ai intrebari?

Am analizat rezultatele. Da, am două clarificări importante înainte să finalizez salvarea: exporturile confirmă corecția consumurilor, dar arată și neconcordanțe ale stocului oficial pe care nu le putem trata ca pe o simplă schimbare de preț.

## 1. Corecția spliturilor este confirmată

Pentru prima operațiune avem:

```text
INVUSEID     = 62256
INVUSELINEID = 164724

209409: QUANTITY=-3; UNITCOST=9,410; LINECOST=28,230
209410: QUANTITY=-1; UNITCOST=9,410; LINECOST=9,410
```

Cantitatea originală din `INVUSELINE` este `4`. Corecția propusă rămâne:


| MATUSETRANSID | Cantitate nouă | PU nou | LINECOST rezultat |
| :-- | --: | --: | --: |
| `209409` | -2 | 9,410 | 18,820 |
| `209410` | -2 | 8,520 | 17,040 |
| Total | -4 |  | 35,860 |

În datele tale, cantitățile ISSUE sunt negative, iar valorile `LINECOST` sunt pozitive; vom păstra această convenție.[^36_1][^36_2]

Lipsa rezultatelor `WORKORDER` este explicată de `REFWO` necompletat pe aceste consumuri. Totuși, ele au destinații de tip activ și conturi GL, deci nu înseamnă că nu există efecte de cost.[^36_1]

## 2. Am identificat un obiect suplimentar care trebuie sincronizat

Fiecare consum are și `INVUSELINESPLITID`:


| MATUSETRANSID | INVUSELINESPLITID |
| :-- | :-- |
| `209409` | `181769` |
| `209410` | `181770` |
| `209419` | `181786` |
| `210144` | `182804` |
| `210145` | `182806` |
| `211307` | `184857` |

Există și relația standard `MATUSETRANS → INVUSELINESPLIT` în configurația exportată. Nu ar fi coerent să schimbăm splitul din `3 + 1` în `2 + 2` numai în `MATUSETRANS`, fără să verificăm înregistrările respective.[^36_3][^36_1]

În plus, trebuie tratate valorile documentului: `INVUSELINE.LINECOST` și `INVUSE.CXTOTALCOST` păstrează acum valoarea `37,640` pentru prima operațiune.[^36_2][^36_4]

Observație tehnică rezolvată: `INVUSELINE` din schema ta nu conține `INVUSEID`. Legarea cu documentul trebuie făcută prin `INVUSENUM + SITEID`, nu printr-un atribut inexistent.[^36_2]

## 3. Problema majoră: straturile oficiale nu sunt reconciliate

Din exporturi rezultă:


| Control | Cantitate |
| :-- | --: |
| `INVBALANCES.CURBAL` | 79 |
| Jurnal recalculat din mișcările `CXSTOCURI` | 79 |
| `SUM(INVLIFOFIFOCOST.QUANTITY)` | 308 |
| Diferență straturi oficiale − sold fizic | 229 |

Straturile oficiale însumează `227` la `9,410` și `81` la `8,520`.[^36_5][^36_6]

În schimb, recalcularea jurnalului din export produce:

```text
9,410 → -12
8,520 →  91
Total →  79
```

După corectarea celor șase ieșiri discutate, repartizarea jurnalului ar deveni:

```text
9,410 →   0
8,520 →  79
Total →  79
```

Așadar, cantitatea fizică totală nu trebuie schimbată pentru această corecție. Dar nu putem aplica pur și simplu ajustări pe straturile oficiale actuale și să declarăm întregul FIFO reconciliat.

Mai există 19 rânduri `CXSTOCURI` cu `CXCURBAL` necompletat în export. Aceste solduri pot fi reconstruite din mișcări, însă scriptul trebuie să trateze explicit această situație.

## 4. Există neconcordanțe și în valorile unor recepții

Am găsit, de exemplu:


| MATRECTRANSID | Cantitate | PU | Cantitate × PU | LINECOST existent |
| :-- | --: | --: | --: | --: |
| `1337462758` | 40 | 9,410 | 376,400 | 188,200 |
| `1337462764` | 12 | 8,520 | 102,240 | 301,120 |

Pentru `1337462764`, straturile oficiale exportate indică încă două rânduri de câte `32` la `9,410`, deși recepția exportată este `12` la `8,520`.[^36_6]

Nu propun să modificăm aceste intrări din butonul de corecție a ieșirilor. Trebuie însă să stabilim explicit ce date considerăm autoritare.

## 5. Întrebările mele

### A. Confirmăm baza de calcul?

Confirmi că, pentru calculul corecției ieșirilor, considerăm corecte cantitățile, prețurile și ordinea curentă din `CXSTOCURI`, inclusiv recepțiile:

```text
1337462758 → 40 la 9,410
1337464898 → 24 la 9,410
1337462764 → 12 la 8,520
```

Valorile și straturile oficiale neconforme nu vor fi folosite pentru a înlocui această bază.

### B. Separăm corecția consumurilor de refacerea straturilor oficiale?

Recomand două operațiuni distincte:

1. Butonul de linie corectează operațiunea ISSUE selectată și reprezentările ei: `MATUSETRANS`, spliturile asociate, valorile documentului și `CXSTOCURI`, fără modificarea cantității fizice.
2. Reconcilierea/refacerea `INVLIFOFIFOCOST` se proiectează separat, deoarece diferența actuală de `229` nu provine doar din cele șase consumuri.

Prima operațiune nu va fi prezentată drept „stoc oficial complet reconciliat” până la rezolvarea celei de-a doua.

## 6. Mai am nevoie de un extras și de codul scripturilor active

Am atașat un fișier SQL scurt cu cele trei selecții suplimentare:

- `INVUSELINESPLIT` pentru cele patru linii de consum;
- sursa scripturilor `CXADDTOCXSTOCURI`, `CXINVLIFOFIFO` și `CXINVUSELINETEST`;
- launch point-urile pentru `INVUSELINESPLIT` și `INVUSE`.

Motivul este concret: configurația arată scripturi active la salvarea `MATUSETRANS`, `INVLIFOFIFOCOST` și `INVUSELINE`. Fără codul lor nu putem ști dacă salvarea corecției va adăuga din nou jurnal, va modifica straturi sau va recalcula alte valori.[^36_7]

Am atașat și două CSV-uri de control cu diferențele găsite.

Nu mai trebuie să retrimiți exporturile deja primite. Am nevoie doar de confirmările A/B și de rezultatele selecțiilor suplimentare pentru a închide partea de salvare fără să presupunem comportamentul automatizărilor locale.

<span style="display:none">[^36_10][^36_11][^36_12][^36_8][^36_9]</span>

<div align="center">⁂</div>

[^36_1]: MATUSETRANS_202610301519.csv

[^36_2]: INVUSELINE_202610301519.csv

[^36_3]: MAXRELATIONSHIP_202610301521.csv

[^36_4]: INVUSE_202610301519.csv

[^36_5]: INVBALANCES_202610301520.csv

[^36_6]: INVLIFOFIFOCOST_202610301521.csv

[^36_7]: SCRIPTLAUNCHPOINT_202610301521.csv

[^36_8]: MAXATTRIBUTE_202610301521.csv

[^36_9]: CXSTOCURI_202610301518.csv

[^36_10]: INVENTORY_202610301520.csv

[^36_11]: ITEM_202610301520.csv

[^36_12]: MATRECTRANS_202610301519.csv


---

# de mentionat. Clientul nu foloseste nimic legat de workorder, hai sa nu ne mai focusam aici!

raspunsurile mele:
a. da
b. da, sa le facem separat

6. le atasez
intrebari?

Am înțeles: clientul nu folosește Work Order și nu mai includem această componentă în implementare.

Confirmările A și B sunt suficiente pentru direcția funcțională:

- `CXSTOCURI` este baza pentru calculul alocării FIFO;
- corectăm operațiunea ISSUE selectată și spliturile ei;
- refacerea `INVLIFOFIFOCOST` rămâne separată.

Am verificat și noile atașamente. Mai am o singură confirmare tehnică, legată de o **protecție** necesară în scriptul existent.

## 1. Spliturile sunt confirmate și în INVUSELINESPLIT

Pentru linia `164724` există exact:


| INVUSELINESPLITID | Cantitate actuală | PU actual |
| :-- | --: | --: |
| `181769` | 3 | 9,410 |
| `181770` | 1 | 9,410 |

Prin urmare, corecția `2 + 2` trebuie sincronizată în ambele obiecte:

```text
MATUSETRANS:
209409 → -2 la 9,410
209410 → -2 la 8,520

INVUSELINESPLIT:
181769 → +2 la 9,410
181770 → +2 la 8,520
```

Aceste legături sunt prezente explicit în exporturi, deci nu mai trebuie deduse din apropierea ID-urilor sau a datelor.[^37_1][^37_2]

Pentru linia `165687`, care are spliturile `3 + 1`, ambele vor putea păstra cantitățile respective dacă întreaga operațiune trebuie consumată la `8,520`. Nu este necesar să le comasăm sau să ștergem un rând doar fiindcă prețul corect devine același.[^37_1]

## 2. Am identificat riscul concret la salvare

În `CXADDTOCXSTOCURI`, ramura:

```python
if launchPoint == "CXNEWMATUSETRANS":
```

adaugă un rând nou în `CXSTOCURI` și îl salvează. În codul furnizat, această ramură nu are o verificare explicită care să limiteze adăugarea la crearea tranzacției.[^37_3]

La corectarea unui `MATUSETRANS` existent trebuie să prevenim o nouă adăugare în jurnal, dacă acel launch point se declanșează și la actualizare. Altfel, noul script ar actualiza rândul existent, iar automatizarea ar putea adăuga încă unul.

`NOACCESSCHECK` sau `NOVALIDATION_AND_NOACTION` pe câmpuri nu trebuie considerate o garanție că scripturile de salvare nu se execută.

## 3. Ce voi păstra în implementare

Noul `CXFIFOFIXISSUE` va:

- modifica numai operațiunea selectată și spliturile ei;
- păstra cantitatea totală consumată;
- sincroniza cantitățile, prețurile și valorile aferente;
- actualiza valorile liniei și totalul documentului;
- recalcula soldurile de jurnal afectate;
- păstra datele și conturile GL;
- nu modifica recepțiile, `INVBALANCES` sau `INVLIFOFIFOCOST`;
- refuza operațiunile deja transmise către EBS sau alte situații neacceptate de handler.

Există deja logică locală de recalculare `CXTOTALCOST`, inclusiv după commit. O voi lua în calcul, fără să declanșez din nou schimbarea statusului documentului.[^37_4][^37_3]

## Singura confirmare rămasă

Confirmi că putem include și ajustarea de protecție în `CXADDTOCXSTOCURI`, astfel încât corectarea unei tranzacții existente să nu genereze un nou rând `CXSTOCURI`, păstrând comportamentul normal la crearea tranzacțiilor?

Nu propun dezactivarea globală a scriptului, ci delimitarea explicită a creării de actualizare. În rest, nu mai am întrebări funcționale.

<div align="center">⁂</div>

[^37_1]: INVUSELINESPLIT_202610301530.csv

[^37_2]: MATUSETRANS_202610301519.csv

[^37_3]: AUTOSCRIPT_202610301531.csv

[^37_4]: SCRIPTLAUNCHPOINT_202610301531.csv


---

# DA ADAUGA PROTECTIA, ASTA E CODUL ACTUAL

\#-------------------------------------------------------------

# AUTOSCRIPT:CXADDTOCXSTOCURI

# DESCRIPTION:item inventory movement to CXSTOCURI

# AUTHOR:Fernando Prajitura

# Created:12-12-2023

# LOGLEVEL:ERROR

# UPDATE: 21.09.2026 - Bug \#1690 Corectie SHIPTRANSFER/SHIPCANCEL

\#-------------------------------------------------------------

# Pentru magaziile sursa normale, CXSTOCURI foloseste COMMODITYGROUP din MATRECTRANS;

# pentru gestiunile speciale se pastreaza codul secundar conform configuratiei LOCATIONS.

from psdi.mbo import Mbo, MboConstants
from psdi.server import MXServer
from psdi.security import UserInfo
from psdi.mbo import SqlFormat
from psdi.webclient.system.session import WebClientSession
from java.io import FileOutputStream

service.log_info('\*\*\* Starting Script CXADDTOCXSTOCURI \*\*\*')

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#

# Define functions

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#

def getAppName():
if app:
return app
wcs = service.webclientsession()
if wcs:
websessionApp = wcs.getCurrentAppId()
if websessionApp:
return websessionApp
parentApp = mbo.getThisMboSet().getParentApp()
if parentApp:
return parentApp
return 'None'

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#

# Running Code

\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#\#

app = getAppName().upper()
userInfo = mbo.getUserInfo()
currentDate = MXServer.getMXServer().getDate()
mxServer = MXServer.getMXServer()
service.log_info('CXADDTOCXSTOCURI script is running from launch point - ' + str(launchPoint) + ' on app - ' + app )
delimitator = '-'
codCustodieInventar ='000' \# default value for cod custodie in inventory
cxCodTipGestiuneInv ='000' \# default value for cod tip gestiune in inventory
\#\#\#\#\#\#\#\#\#\#\#

# mbo INVTRANS

\#\#\#\#\#\#\#\#\#\#\#
if launchPoint == 'CXNEWINVTRANS':
\# \# inventory adjustments only
if mbo.getString('TRANSTYPE') == 'RECBALADJ':

```
    #verifica daca au fost selectate Centru de Cost si Activitate 
    if (app =='CXINVENTOR'):
        contCheltuieli = mbo.getString('GLDEBITACCT')
        contDeVerificat = contCheltuieli.split(delimitator, 5)
        #service.log_info('*** Cont ajustari  ***' + contDeVerificat[2] + '...'+contDeVerificat[4] ) 
    if (contDeVerificat[2] == '00000' or contDeVerificat[4] == '00000'):
        service.error("CXINVADJ", "CXCentruCostActivitate")
        
    # set cod tip gestiune din inventar daca are valoare acolo
    articolInventar = mbo.getMboSet('$CXArtInventar', 'INVENTORY', "location=:STORELOC and siteid=:siteid and itemnum=:itemnum").getMbo(0)
    articol = mbo.getMboSet('$CXItem', 'ITEM', "itemnum=:itemnum").getMbo(0)
    cxCodTipGestuneItem = articol.getString("COMMODITYGROUP")
    cxCodTipGestiuneInv = articolInventar.getString("CXCODTIPGESTIUNE")
    if cxCodTipGestiuneInv:
        cxCodTipGestiune = cxCodTipGestiuneInv
    else:
        cxCodTipGestiune = cxCodTipGestuneItem
        
    # get document date from count date in INVBALANCES for item/storeroom
    invBalMbo = mbo.getMboSet('$CXinvBal', 'INVBALANCES', "location=:STORELOC and siteid=:siteid and itemnum=:itemnum").getMbo(0)
        
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("STORELOC"))
    linieStocMbo.setValue("COMMODITYGROUP",cxCodTipGestiune)
    linieStocMbo.setValue("CXDOCUMENTDATE",invBalMbo.getDate("PHYSCNTDATE"))
    linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("NEWCOST"))
    linieStocMbo.setValue("CXREFMBO","INVTRANS")
    linieStocMbo.setValue("CXREF",mbo.getString("TRANSTYPE"))
    linieStocMbo.setValue("CXREFID",mbo.getLong("INVTRANSID"))
    # linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    # linieStocMbo.setValue("CURRENCYCODE","RON")
    
    linieStocMbo.getThisMboSet().save()
```

\#\#\#\#\#\#\#\#\#\#\#

# mbo INVLIFOFIFOCOST

\#\#\#\#\#\#\#\#\#\#\#

\#\#\#\#\#\#\#\#\#\#\#

# mbo MATUSETRANS

\#\#\#\#\#\#\#\#\#\#\#

if launchPoint == 'CXNEWMATUSETRANS':
\# get values from INVENTORY where ITEMNUM and FROMSTORELOC - disabled; will overwrite invuseline selection if different from inventory
\# set cod tip gestiune din inventar daca are valoare acolo
\# articolInventar = mbo.getMboSet('\$CXArtInventar', 'INVENTORY', "location=:STORELOC and siteid=:siteid and itemnum=:itemnum").getMbo(0)

```
# get from INVUSELINE by INVUSELINEID    
articolInvUseLine = mbo.getMboSet('$CXArtInvUseLine', 'INVUSELINE', "invuselineid=:invuselineid").getMbo(0)
# aduce cod custodie daca exista in inventory
if articolInvUseLine:
    if not articolInvUseLine.isNull('CXCODCUSTODIE'):
        codCustodieInventar =  articolInvUseLine.getString('CXCODCUSTODIE')


# check action that triggered this
# speta ISSUE
if mbo.getString('ISSUETYPE') == 'ISSUE':
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("STORELOC"))
    if codCustodieInventar  != '000':
        #linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
        linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
    else:
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATUSETRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATUSETRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    if not mbo.isNull('ROTASSETNUM'):
        linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
    
    linieStocMbo.getThisMboSet().save()
    
# speta RETURN
if mbo.getString('ISSUETYPE') == 'RETURN':
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("STORELOC"))
    if codCustodieInventar  != '000':
        #linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
        linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
    else:
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATUSETRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATUSETRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    
    linieStocMbo.getThisMboSet().save()
```

\#\#\#\#\#\#\#\#\#\#\#

# mbo MATRECTRANS

\#\#\#\#\#\#\#\#\#\#\#

if launchPoint == 'CXNEWMATRECTRANS':
\# 2 linii de introdus: iesirea din fromstoreloc si intrarea in tostoreloc

```
articolInvUseLine = mbo.getMboSet('$CXArtInvUseLine', 'INVUSELINE', "invuselineid=:invuselineid").getMbo(0)
if articolInvUseLine:
    if not articolInvUseLine.isNull('CXCODCUSTODIE'):
        codCustodieInventar =  articolInvUseLine.getString('CXCODCUSTODIE')
        


# speta SHIPTRANSFER
if mbo.getString('ISSUETYPE') == 'SHIPTRANSFER':
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("FROMSTORELOC"))
    # Bug #1690 - cod secundar doar pentru gestiuni sursa speciale;
    # pentru magazii normale se pastreaza COMMODITYGROUP din MATRECTRANS.
    gestiuneSursa = mbo.getMboSet('$CXGestiuneSursa1690', 'LOCATIONS', "location=:fromstoreloc and siteid=:fromsiteid").getMbo(0)
    gestiuneSursaSpeciala = False
    if gestiuneSursa:
        gestiuneSursaSpeciala = (
            gestiuneSursa.getBoolean('CXCUSTODIE') or
            gestiuneSursa.getBoolean('CXCUSTODIETERTI') or
            gestiuneSursa.getBoolean('CXCUSTODIELASATATERTI') or
            gestiuneSursa.getBoolean('CXGESTIUNEMARFURI') or
            gestiuneSursa.getBoolean('CXGESTIUNEFINITE') or
            gestiuneSursa.getBoolean('CXGESTIUNEALIMENTATIEPUBLICA')
        )
    if gestiuneSursaSpeciala and codCustodieInventar != '000':
        linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
    else:
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    #   negative qty value for exit
    linieStocMbo.setValue("CXQTY",(-mbo.getDouble("QUANTITY")))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    #adaugam persoana catre care se face transferul si articolul rotativ
    #linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
    #linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
    if not mbo.isNull('ISSUETO'):
        linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
    if not mbo.isNull('ROTASSETNUM'):
        linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))                                                    
    
    linieStocMbo.getThisMboSet().save()

# speta SHIPCANCEL

if mbo.getString('ISSUETYPE') == 'SHIPCANCEL':
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("FROMSTORELOC"))
    # Bug #1690 - cod secundar doar pentru gestiuni sursa speciale;
    # pentru magazii normale se pastreaza COMMODITYGROUP din MATRECTRANS.
    gestiuneSursa = mbo.getMboSet('$CXGestiuneSursa1690', 'LOCATIONS', "location=:fromstoreloc and siteid=:fromsiteid").getMbo(0)
    gestiuneSursaSpeciala = False
    if gestiuneSursa:
        gestiuneSursaSpeciala = (
            gestiuneSursa.getBoolean('CXCUSTODIE') or
            gestiuneSursa.getBoolean('CXCUSTODIETERTI') or
            gestiuneSursa.getBoolean('CXCUSTODIELASATATERTI') or
            gestiuneSursa.getBoolean('CXGESTIUNEMARFURI') or
            gestiuneSursa.getBoolean('CXGESTIUNEFINITE') or
            gestiuneSursa.getBoolean('CXGESTIUNEALIMENTATIEPUBLICA')
        )
    if gestiuneSursaSpeciala and codCustodieInventar != '000':
        linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar)
    else:
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",(mbo.getDouble("QUANTITY")))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    
    linieStocMbo.getThisMboSet().save()

# speta SHIPRECEIPT
if mbo.getString('ISSUETYPE') == 'SHIPRECEIPT':
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    
    if mbo.getString('ROTASSETNUM') is not None and mbo.getString('ROTASSETNUM').strip() != "" and mbo.getString('TOSTORELOC').startswith('H') :
       
        tostorelocMbo = mbo.getMboSet('$CXArtNomenclator', 'INVUSELINE', "invuselineid=:invuselineid").getMbo(0)
        if tostorelocMbo:
            linieStocMbo.setValue("LOCATION",tostorelocMbo.getString("TOSTORELOC"))
    else:
        linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
    
    if mbo.getString('CXCODCUSTODIE') is not None and mbo.getString('CXCODCUSTODIE').strip() != "":
    
    #if codCustodieInventar != '000':
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString('CXCODCUSTODIE') )
    else:
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    #adaugam persoana care a receptionat transferul si articolul rotativ
    if not mbo.isNull('ISSUETO'):
        linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
    if not mbo.isNull('ROTASSETNUM'):
        linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
                                                                        
    linieStocMbo.getThisMboSet().save()

#   speta VOIDSHIPRECEIPT
if mbo.getString('ISSUETYPE') == 'VOIDSHIPRECEIPT':
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
    if codCustodieInventar != '000':
        linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar )
    else:
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",(mbo.getDouble("QUANTITY")))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    
    linieStocMbo.getThisMboSet().save()

#   speta SHIPRETURN
if mbo.getString('ISSUETYPE') == 'SHIPRETURN':
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add 2 lines to CXSTOCURI for source and destination
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    cxCodCustodie = mbo.getString("CXCODCUSTODIE")
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("FROMSTORELOC"))
    if codCustodieInventar != '000':
        linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar )
    elif cxCodCustodie:
        # are valoare și nu e string gol
        linieStocMbo.setValue("COMMODITYGROUP", cxCodCustodie)
    else:
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",(-mbo.getDouble("QUANTITY")))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    
    linieStocMbo.getThisMboSet().save()
    
    # add for destination negative value
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
    linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",(mbo.getDouble("QUANTITY")))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    
    linieStocMbo.getThisMboSet().save()
    
    


#   speta RECEIPT        
if mbo.getString('ISSUETYPE') == 'RECEIPT':
    
    
    # set cod tip gestiune din inventar daca are valoare acolo
    articolInventar = mbo.getMboSet('$CXArtInventar', 'INVENTORY', "location='" + str(mbo.getString("POLINE.STORELOC")) + "' and siteid=:siteid and itemnum=:itemnum").getMbo(0)
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    service.log_info('*** XXXXXXXXXXXXXXXXXXXXXXXXXXXX ***')
    service.log_info('*** '+ mbo.getString("COMMODITYGROUP")+ '***')
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))                                                                                                   
    # get storeroom info from related POLINE - introduced by rotating assets receiving to avoid holding location
    #linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
    linieStocMbo.setValue("LOCATION",mbo.getString("POLINE.STORELOC"))
    if mbo.isNull('CXCODCUSTODIE'):
        
        # cod gestiune din gestiunea destinatie if exists
        if articolInventar != None:
            
            cxCodTipGestiuneInv = articolInventar.getString("CXCODTIPGESTIUNE")
        if cxCodTipGestiuneInv and cxCodTipGestiuneInv.strip() != "000":
        #if cxCodTipGestiuneInv !="000":
            
            cxCodTipGestiune = cxCodTipGestiuneInv
        else:
            #service.log_info('*** else XXXXXXXXXXXXXXXXXXXXXXXXXXXX'+ mbo.getString("COMMODITYGROUP")+' ***')
            cxCodTipGestiune = mbo.getString("COMMODITYGROUP")
        linieStocMbo.setValue("COMMODITYGROUP",cxCodTipGestiune)
    else:
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("CXCODCUSTODIE"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    if not mbo.isNull('ROTASSETNUM'):
        linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))   
        
    linieStocMbo.getThisMboSet().save()

# speta TRANSFER
# add 2 lines to CXSTOCURI; one for transfer out, another for transfer in
#service.log_info('*** AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA ***')
if mbo.getString('ISSUETYPE') == 'TRANSFER' and not mbo.isNull('FROMSTORELOC'):
    #service.log_info('*** XXXXXXXXXXXXXXXXXX XXXXXXXXXXXXXXXXXXXXXXXXXXXX ***')
    #service.log_info('*** ZZZZZZZZZZZZZZZZZZZZZZ XXXXXXXXXXXXXXXXXXXXXXXXXXXX ***')
    LocSet = mxServer.getMboSet("LOCATIONS", userInfo)
    LocSet.setWhere("location='"+mbo.getString('FROMSTORELOC')+"'")
    LocSet.reset()
    Loc = LocSet.getMbo(0)
    
    if Loc:
        tipLocDest = Loc.getString('TYPE')
        if tipLocDest!='HOLDING':
            cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
            # add line for transfer out
            linieStocMbo=cxStocuriMboSet.addAtEnd()
            
            linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
            linieStocMbo.setValue("SITEID",mbo.getString("FROMSITEID"))
            linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
            linieStocMbo.setValue("LOCATION",mbo.getString("FROMSTORELOC"))
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
            linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
            #   negative qty value for exit
            linieStocMbo.setValue("CXQTY",(-mbo.getDouble("QUANTITY")))
            linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
            linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
            linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
            linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
            linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
            linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
            linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
            linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
            #adaugam persoana catre care se face transferul si articolul rotativ
            #linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
            #linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
            if not mbo.isNull('ISSUETO'):
                linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
            if not mbo.isNull('ROTASSETNUM'):
                linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))                                                    
            
            linieStocMbo.getThisMboSet().save()
            
            # add line for transfer in
            linieStocMbo=cxStocuriMboSet.addAtEnd()
            
            linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
            linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
            linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
            linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
            linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
            linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
            #   negative qty value for exit
            linieStocMbo.setValue("CXQTY",(mbo.getDouble("QUANTITY")))
            linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
            linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
            linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
            linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
            linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
            linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
            linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
            linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
            #adaugam persoana catre care se face transferul si articolul rotativ
            #linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
            #linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))
            if not mbo.isNull('ISSUETO'):
                linieStocMbo.setValue("ISSUETO",mbo.getString("ISSUETO"))
            if not mbo.isNull('ROTASSETNUM'):
                linieStocMbo.setValue("ROTASSETNUM",mbo.getString("ROTASSETNUM"))                                                    
            
            linieStocMbo.getThisMboSet().save()
    LocSet.close()   
#   speta RETURN
if mbo.getString('ISSUETYPE') == 'RETURN':
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
    linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    
    linieStocMbo.getThisMboSet().save()
    
#   speta VOIDRECEIPT
if mbo.getString('ISSUETYPE') == 'VOIDRECEIPT':
    
    
    cxStocuriMboSet=mxServer.getMboSet("CXSTOCURI", userInfo)
    # add new line to CXSTOCURI
    linieStocMbo=cxStocuriMboSet.addAtEnd()
    cxCodCustodie = mbo.getString("CXCODCUSTODIE")
    linieStocMbo.setValue("ITEMNUM", mbo.getString("ITEMNUM"))
    linieStocMbo.setValue("SITEID",mbo.getString("SITEID"))
    linieStocMbo.setValue("ORGID",mbo.getString("ORGID"))
    linieStocMbo.setValue("LOCATION",mbo.getString("TOSTORELOC"))
    if codCustodieInventar != '000':
        linieStocMbo.setValue("COMMODITYGROUP",codCustodieInventar )
    elif cxCodCustodie:
        # are valoare și nu e string gol
        linieStocMbo.setValue("COMMODITYGROUP", cxCodCustodie)
    else:
        linieStocMbo.setValue("COMMODITYGROUP",mbo.getString("COMMODITYGROUP"))
    
    linieStocMbo.setValue("CXDOCUMENTDATE",mbo.getDate("ACTUALDATE"))
    linieStocMbo.setValue("CXQTY",mbo.getDouble("QUANTITY"))
    linieStocMbo.setValue("UNITCOST",mbo.getDouble("UNITCOST"))
    linieStocMbo.setValue("CXREF",mbo.getString("ISSUETYPE"))
    linieStocMbo.setValue("CXREFMBO","MATRECTRANS")
    linieStocMbo.setValue("CXREFID",mbo.getLong("MATRECTRANSID"))
    linieStocMbo.setValue("DESCRIPTION",mbo.getString("DESCRIPTION"))
    linieStocMbo.setValue("GLCREDITACCT",mbo.getString("GLCREDITACCT"))
    linieStocMbo.setValue("GLDEBITACCT",mbo.getString("GLDEBITACCT"))
    linieStocMbo.setValue("CURRENCYCODE",mbo.getString("CURRENCYCODE"))
    
    linieStocMbo.getThisMboSet().save()
```

Am adăugat **protecția** și am atașat scriptul complet `CXADDTOCXSTOCURI_PROTEJAT`, cu 629 de linii.

Am păstrat autorul original, Fernando Prajitura, și am adăugat actualizarea din `30.10.2026 — Cristian Grosu`.

## 1. Cum funcționează protecția

Ramura `CXNEWMATUSETRANS` se execută acum numai dacă funcția de control permite crearea jurnalului:

```python
if launchPoint == 'CXNEWMATUSETRANS' and shouldCreateMatUseJournal():
```

Funcția verifică:


| Situație | Comportament |
| :-- | :-- |
| `MATUSETRANS` nou | Permite logica existentă de creare în `CXSTOCURI` |
| Actualizarea unui `MATUSETRANS` existent | Nu adaugă alt rând în jurnal |
| Ștergere | Nu adaugă rând în jurnal |
| Tranzacție nouă, dar jurnalul există deja pentru același `MATUSETRANSID` | Nu mai adaugă încă unul |

Pentru identificarea creării folosesc prioritar variabila implicită `onadd`, furnizată de Maximo. `onupdate` indică actualizarea; verificarea `mbo.toBeAdded()` este doar fallback dacă variabilele nu sunt disponibile. Aceste variabile sunt documentate de IBM pentru diferențierea operațiunilor MBO.[^38_1]

Verificarea suplimentară de existență folosește:

```text
CXREFMBO = 'MATUSETRANS'
CXREFID  = MATUSETRANSID
```

Aceasta reduce riscul de duplicare la o reluare a evenimentului; nu înlocuiește o constrângere unică sau un control de concurență la nivel de bază de date.

## 2. Ce am păstrat neschimbat

- Logica de creare a jurnalului pentru `ISSUE` și `RETURN`.
- Regulile `MATRECTRANS`, inclusiv corecția Bug \#1690.
- Regulile pentru gestiunile speciale și codurile de custodie.
- Cantitățile, semnele, prețurile și câmpurile copiate de ramurile existente.

Protecția nouă se aplică ramurii `MATUSETRANS`; nu am schimbat comportamentul de inserare al ramurii `MATRECTRANS`.

## 3. Două corecții tehnice incluse

- Am corectat indentarea și accesul la context în `getAppName()`.
- Am mutat verificarea `contDeVerificat` în interiorul condiției `app == 'CXINVENTOR'`, unde variabila este inițializată, și am verificat numărul segmentelor înainte de accesarea lor.


## 4. Instalare și test

1. Păstrează o copie a codului actual.
2. Deschide Automation Scripts → `CXADDTOCXSTOCURI`.
3. Înlocuiește întregul conținut cu fișierul atașat.
4. Salvează. Nu schimba numele scriptului sau launch point-urile.

În instanța de test verifică:

- un consum nou creează jurnalul normal;
- un retur nou creează jurnalul normal;
- actualizarea unei tranzacții existente nu crește numărul rândurilor `CXSTOCURI` pentru acel `MATUSETRANSID`.

Am verificat sintaxa și am testat separat funcția de protecție pentru creare, actualizare, ștergere și jurnal deja existent. Execuția în Maximo/Jython trebuie confirmată.

Această modificare nu sincronizează automat jurnalul când se schimbă un consum existent. Sincronizarea va fi făcută explicit de `CXFIFOFIXISSUE`; rolul protecției este să împiedice adăugarea unui rând suplimentar în timpul acelei corecții.

<span style="display:none">[^38_10][^38_11][^38_12][^38_13][^38_14][^38_15][^38_2][^38_3][^38_4][^38_5][^38_6][^38_7][^38_8][^38_9]</span>

<div align="center">⁂</div>

[^38_1]: https://www.ibm.com/docs/en/masv-and-l/maximo-manage/cd?topic=bindings-implicit-variables

[^38_2]: https://www.ibm.com/support/pages/saving-time-automation-scripts

[^38_3]: https://www.ibm.com/support/pages/automation-scripting-–-attribute-launch-point-–-using-onadd

[^38_4]: https://www.ibm.com/support/pages/collection-automation-scripts

[^38_5]: https://www.ibm.com/docs/es/maximo-eam-saas?topic=scripts-implicit-variables

[^38_6]: https://www.ibm.com/docs/en/control-desk/7.6.1?topic=scripts-implicit-variables

[^38_7]: https://bportaluri.com/blog/2019/11/maximo-scripting-before-after-save-commit/

[^38_8]: https://a3jgroup.com/launch-automation-script-on-new-record-creation-in-maximo/

[^38_9]: https://bportaluri.com/blog/2019/11/maximo-scripting-the-mbo-add-method/

[^38_10]: https://community.ibm.com/HigherLogic/System/DownloadDocumentFile.ashx?DocumentFileKey=cea4b78e-5592-4e2d-b107-dc3f473f560b

[^38_11]: https://www.scribd.com/document/626451147/Maximo-76-Scripting-Features

[^38_12]: https://moremaximo.com/question/script-auto-infinite-loop

[^38_13]: http://maximotip.blogspot.com/2019/07/maximo-automation-script-setting-values.html

[^38_14]: https://www.linkedin.com/posts/ravi-raj-singh-75481a1b4_ibmmaximo-automationscripting-maximodeveloper-activity-7422633235026767872-E3Lb

[^38_15]: https://ghost.maximoinsider.com/maximo-automation-scripts-launch-points-production-patterns/


---

# de ce primesc aceasta eroare la check fifo?

Mesajul indică o problemă de **context al butonului**, nu o eroare în calculul FIFO. Scriptul a fost pornit, dar obiectul primit în variabila `mbo` nu a trecut verificarea pentru `INVENTORY`. De aceea afișează „Audit local oprit: Ruleaza Check FIFO din INVENTORY”.[^40_1]

## De ce se poate întâmpla

În `CXINVAUDIT` avem verificarea:

```python
if inventory is None or inventory.getName() != "INVENTORY":
    raise ValueError("Ruleaza Check FIFO din INVENTORY")
```

În captura actuală, butonul `Check FIFO` este poziționat lângă tabelul de costuri LIFO/FIFO. Dacă a fost introdus în contextul acelui tabel, poate transmite rândul `INVLIFOFIFOCOST`, nu înregistrarea principală `INVENTORY`.

Aceasta este explicația probabilă; mesajul actual nu ne spune ce obiect a primit efectiv. Mai trebuie eliminată și posibilitatea unei diferențe de litere mari/mici în numele obiectului.

Nu este o dovadă că modificarea `CXADDTOCXSTOCURI` a produs problema.

## Corecție sigură în CXINVAUDIT

Putem accepta și situația în care butonul transmite un rând copil, dar numai dacă putem găsi `INVENTORY` în lanțul său de proprietari. Nu eliminăm pur și simplu verificarea.

### 1. Adaugă această funcție înainte de `run_local()`

```python
def resolve_inventory(context):
    if context is None:
        raise ValueError("Check FIFO nu a primit niciun obiect MBO")

    current = context
    visited = []

    for index in range(10):
        if current is None:
            break

        name = txt(current.getName()).upper()
        visited.append(name)

        if name == "INVENTORY":
            return current

        current = current.getOwner()

    raise ValueError(
        "Context Check FIFO incorect. Obiecte primite/parinte: "
        + " -> ".join(visited)
        + ". Butonul trebuie legat la INVENTORY."
    )
```


### 2. Modifică începutul funcției `run_local()`

Din:

```python
def run_local(inventory,script_service):
    from psdi.mbo import MboConstants
    if inventory is None or inventory.getName()!="INVENTORY":
        raise ValueError("Ruleaza Check FIFO din INVENTORY")
```

în:

```python
def run_local(inventory,script_service):
    from psdi.mbo import MboConstants
    inventory = resolve_inventory(inventory)
```

Restul funcției rămâne neschimbat, începând cu:

```python
    for f in ("ITEMNUM","SITEID","LOCATION"):
```


## Ce rezultat obținem

- Dacă butonul transmite `INVENTORY`, auditul continuă normal.
- Dacă transmite un copil al cărui proprietar este `INVENTORY`, scriptul folosește înregistrarea principală.
- Dacă nu există un părinte `INVENTORY`, auditul se oprește și afișează obiectele efectiv primite, fără să auditeze arbitrar alt articol.

Dacă apare, de exemplu:

```text
Context Check FIFO incorect.
Obiecte primite/parinte: INVLIFOFIFOCOST.
Butonul trebuie legat la INVENTORY.
```

atunci trebuie corectată sursa de date/contextul controlului în Application Designer. Nu introduce un `Target ID` presupus și nu schimba launch point-ul pe `INVLIFOFIFOCOST`: obiectul acțiunii `Check FIFO` trebuie să rămână `INVENTORY`.

<div align="center">⁂</div>

[^40_1]: image.jpg


---

# cand apas pe butonul 2 pe linia cu matusetransid=209409 primesc aceasta eroare

Eroarea este cauzată de importul **`decimal`** din script:

```text
ImportError: No module named decimal
```

Mediul Jython al instanței tale nu găsește acest modul. Scriptul se oprește la import, înainte să ajungă la analiza sau corecția tranzacției `209409`. Nu este o problemă a cantității ori a prețului acelui rând.[^41_1]

Importul respectiv provine din versiunea de analiză pe care am livrat-o anterior — trebuie adaptat mediului tău.

## Corecția necesară

Trebuie înlocuit calculul bazat pe:

```python
from decimal import Decimal, getcontext
```

cu aritmetică Java:

```python
from java.math import BigDecimal, MathContext, RoundingMode
```

Aceasta este abordarea folosită și în `CXINVAUDIT`.

Nu este suficient să schimbăm doar importul: trebuie adaptate operațiile aritmetice, comparațiile, rotunjirea și formatarea. Nu recomand conversia la `float` sau `double` pentru calculele de cost.

## Mai există o adaptare necesară în versiunea veche

Din exportul tău, `INVUSELINE` nu are câmpul `INVUSEID`. Scriptul trebuie să identifice documentul prin `INVUSENUM + SITEID`, păstrând `INVUSELINEID` pentru identificarea liniei. Altfel, după remedierea importului, vechiul cod poate eșua la această verificare.[^41_2]

## Atenție la versiunea de pe buton

Versiunea `CXFIFOFIXISSUE` livrată anterior în această conversație era `PLAN-ONLY`: calcula propunerea, dar nu salva corecțiile. Protecția adăugată în `CXADDTOCXSTOCURI` nu o transformă într-un script de update.

Pentru a remedia integral codul fără să îți suprascriu eventuale modificări locale, atașează conținutul actual al scriptului `CXFIFOFIXISSUE` din Maximo. Nu mai sunt necesare alte extrase de date; este necesar doar codul care rulează acum pe butonul nr. 2.

<div align="center">⁂</div>

[^41_1]: image.jpg

[^41_2]: INVUSELINE_202610301519.csv


---

# asa e ok?

Importul Java este corect, dar **nu** este suficient pentru a confirma că întregul script va funcționa. În captură ai și un import duplicat pentru `BigDecimal`; îl poți elimina.[^42_1]

## Blocul de importuri poate rămâne astfel

```python
from java.math import BigDecimal, MathContext, RoundingMode
from java.text import NumberFormat, ParsePosition
from java.util import Locale, TimeZone
from psdi.server import MXServer
from psdi.mbo import MboConstants, SqlFormat
from psdi.util import MaxType
import json
```


## Ce mai trebuie verificat

Dacă ai înlocuit doar:

```python
from decimal import Decimal, getcontext
```

cu importul Java, restul codului poate utiliza încă:

```python
Decimal(...)
getcontext().prec = 34
```

sau operații/metode specifice `Decimal`. Acestea trebuie convertite coerent la `BigDecimal`; simpla schimbare a importului nu face conversia.

De exemplu, pentru obiecte Java `BigDecimal`, operațiile explicite sunt:

```python
a.add(b)
a.subtract(b)
a.multiply(b)
a.divide(b, MathContext(34, RoundingMode.HALF_EVEN))
a.compareTo(b)
```

Nu recomand o înlocuire globală mecanică `Decimal` → `BigDecimal`, fără verificarea calculelor și a rotunjirilor.

În captură văd `VERSION = "2.0-APPLY-ISSUE"`, deci nu trebuie să presupunem că rulezi versiunea veche `PLAN-ONLY`. Pentru un script care poate salva modificări, trebuie verificat codul complet înainte de execuție.[^42_1]

Atașează varianta actuală integrală `CXFIFOFIXISSUE`, ca fișier `.py` sau `.txt`, inclusiv modificarea importurilor. Îți pot corecta astfel exact versiunea instalată, fără să pierdem logica de update existentă.

<div align="center">⁂</div>

[^42_1]: image.jpg


---

# mai bine da-mi scriptul cap coada

Am atașat scriptul **complet** `CXFIFOFIXISSUE`, versiunea `2.1-APPLY-ISSUE-JAVA`, cu 749 de linii. Nu este un fragment de înlocuit și nu mai folosește modulele Python `decimal`, `json` sau `re`.

Calculele folosesc `java.math.BigDecimal`. Nu mai trebuie să modifici manual importurile.

## Ce face această versiune

La apăsarea butonului nr. 2 pe un rând `ISSUE / MATUSETRANS`:

1. Identifică operațiunea prin `INVUSEID + INVUSELINEID`.
2. Citește toate spliturile acelei operațiuni.
3. Reconstruiește alocarea FIFO din intrările anterioare din `CXSTOCURI`.
4. Redistribuie cantitatea totală între spliturile existente.
5. Actualizează împreună:
    - `MATUSETRANS`: cantitate, costuri, valori și proveniență;
    - `INVUSELINESPLIT`: cantitate și preț;
    - `INVUSELINE`: prețul echivalent și valoarea liniei;
    - `INVUSE.CXTOTALCOST`;
    - `CXSTOCURI`: cantitățile/prețurile operațiunii și soldurile afectate, inclusiv soldurile ulterioare lipsă.

Legăturile dintre consumuri și spliturile oficiale sunt cele din exporturile tale, nu sunt deduse din ID-uri consecutive.[^43_1][^43_2]

Nu modifică datele tranzacțiilor, cantitățile sau prețurile recepțiilor, `INVBALANCES` ori `INVLIFOFIFOCOST`. Reconcilierea straturilor oficiale rămâne separată.

## Rezultatul testat pentru prima operațiune

Pentru apăsarea pe `209409` sau `209410`, planul numeric testat este:


| MATUSETRANSID | Cantitate nouă | PU nou | LINECOST nou | MATRECTRANSID sursă |
| :-- | --: | --: | --: | :-- |
| `209409` | -2 | 9,410 | 18,820 | `1337464898` |
| `209410` | -2 | 8,520 | 17,040 | `1337462764` |

Cantitatea liniei rămâne `4`, valoarea devine `35,860`, iar prețul echivalent al liniei este `8,965`.

Pentru grupul `210144 + 210145`, scriptul poate păstra spliturile `3 + 1`, actualizând ambele prețuri la `8,520`; nu le comasează inutil.

## Protecții importante

Scriptul:

- verifică instalarea protecției `CXADDTOCXSTOCURI`;
- nu creează și nu șterge `MATUSETRANS`;
- păstrează cantitatea totală a operațiunii;
- refuză intrările, retururile și operațiunile `MOTIV=ORDINE_DATE`;
- refuză surse transmise către EBS, retururi asociate și conversii neimplementate;
- cere corectarea unei diferențe FIFO anterioare înainte de a sări la una ulterioară;
- reverifică datele înaintea scrierii;
- păstrează istoricul intervenției în descrierea lungă a tranzacțiilor `MATUSETRANS`.

Salvarea este coordonată printr-o tranzacție MBO, cu verificări între `save()` și `commit()`. API-ul Maximo permite această separare a etapelor.[^43_3]

Există și un control după commit pentru schimbări neașteptate ale stocului oficial sau ale numărului de rânduri din jurnal. Dacă apare o astfel de avertizare, trebuie oprite corecțiile următoare; un control după commit nu poate garanta anularea salvărilor independente făcute de alte automatizări.

## Instalare

1. Păstrează o copie a scriptului actual.
2. Deschide Automation Scripts → `CXFIFOFIXISSUE`.
3. Înlocuiește integral codul cu fișierul atașat.
4. Păstrează configurația existentă:

```text
Action / Launch Point: CXFIFOFIXISSUE
Object:                CXSTOCURI
Event:                 CXFIFOFIXISSUE
Message:               CXFIFO / FIXISSUERESULT / {0}
```

5. Fă prima execuție în TEST, pe `209409`, cu protecția instalată și fără procese concurente care reconstruiesc jurnalul.
6. După mesajul `SALVAT`, apasă `Check FIFO`. Textul vechi din „Info FIFO” poate rămâne vizibil până la rerularea auditului.

Aceasta este o versiune care salvează efectiv, nu `PLAN-ONLY` și nu dry-run.

Am verificat sintaxa și am testat algoritmul numeric pe CSV-urile tale, inclusiv cele patru operațiuni și soldurile finale simulate `0` la `9,410`, respectiv `79` la `8,520`. Am atașat și rezultatul acestor teste. Nu am executat codul în Maximo/Jython; validarea integrării MBO și a efectelor automatizărilor locale trebuie făcută în instanța de test.

<span style="display:none">[^43_10][^43_11][^43_12][^43_13][^43_14][^43_15][^43_16][^43_17][^43_18][^43_19][^43_4][^43_5][^43_6][^43_7][^43_8][^43_9]</span>

<div align="center">⁂</div>

[^43_1]: MATUSETRANS_202610301519.csv

[^43_2]: INVUSELINESPLIT_202610301530.csv

[^43_3]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/txn/MXTransaction.html

[^43_4]: image.jpg

[^43_5]: image.jpg

[^43_6]: https://learn.microsoft.com/en-us/sql/t-sql/language-elements/save-transaction-transact-sql?view=sql-server-ver17

[^43_7]: https://www.ibm.com/docs/en/masv-and-l/maximo-manage/cd?topic=scripts-scripting-best-practices

[^43_8]: https://bportaluri.com/wp-content/MaximoJavaDocs7612/psdi/txn/MXTransactionImpl.html

[^43_9]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/mbo/MboSet.html

[^43_10]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/app/assetcatalog/SpecificationMboSet.html

[^43_11]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/txn/class-use/MXTransaction.html

[^43_12]: https://bportaluri.com/wp-content/MaximoJavaDocs7612/psdi/app/workorder/AssignmentSet.html

[^43_13]: https://community.ibm.com/community/user/discussion/what-is-the-correct-way-to-close-a-mboset

[^43_14]: https://community.ibm.com/community/user/discussion/the-rules-about-when-to-close-an-mboset-are-a-bit-confusing

[^43_15]: https://eam-maximodev-tehcnofunctional.blogspot.com/2020/01/maximodevmaximo-mbo-transactions-and.html

[^43_16]: https://thatmaximoguy.blogspot.com/2015/08/dynamically-adding-transactable.html

[^43_17]: https://community.ibm.com/community/user/viewdocument/maximo-business-object-development?CommunityKey

[^43_18]: http://thatmaximoguy.blogspot.com/2015/08/

[^43_19]: https://bportaluri.com/wp-content/downloads/MaximoAutomationScriptsQuickReference.pdf


---

# acum primesc eroarea

Acum este o problemă de configurare a **mesajului**: Maximo afișează identificatorul:

```text
cxfifo#FIXISSUERESULT
```

în locul textului transmis de script. Asta indică faptul că mesajul pentru grupul/cheia respectivă nu a fost rezolvat — poate lipsi, poate avea alte identificatoare sau poate să nu fie încă disponibil în cache. Din acest popup nu putem afla rezultatul real al corecției.[^44_1]

## 1. Nu apăsa repetat butonul înainte să verifici datele

Scriptul folosește același mesaj final atât pentru un rezultat `SALVAT`, cât și pentru o oprire controlată. Prin urmare, popup-ul nu dovedește că salvarea a eșuat.

Verifică întâi:

```sql
SELECT
    MATUSETRANSID,
    QUANTITY,
    UNITCOST,
    ACTUALCOST,
    LINECOST,
    MATRECTRANSID
FROM MATUSETRANS
WHERE MATUSETRANSID IN (209409, 209410)
ORDER BY MATUSETRANSID;
```

Dacă vezi deja:


| MATUSETRANSID | QUANTITY | UNITCOST | LINECOST |
| :-- | --: | --: | --: |
| `209409` | -2 | 9,410 | 18,820 |
| `209410` | -2 | 8,520 | 17,040 |

înseamnă că cel puțin aceste actualizări au fost salvate și trebuie verificat rezultatul complet, nu repetată imediat operațiunea.

## 2. Soluția rapidă: reutilizează mesajul funcțional de la Check FIFO

În `CXFIFOFIXISSUE`, caută:

```python
MESSAGE_GROUP = "CXFIFO"
MESSAGE_KEY = "FIXISSUERESULT"
```

Înlocuiește cu:

```python
MESSAGE_GROUP = "CXCHECKFIFO"
MESSAGE_KEY = "RESULT"
```

La finalul scriptului păstrezi:

```python
service.error(MESSAGE_GROUP, MESSAGE_KEY, [result])
```

Acest grup/cheie este deja folosit de `CXINVAUDIT` în configurația ta. Modificarea schimbă numai afișarea rezultatului, nu calculele sau salvarea.

## 3. Alternativ: configurează mesajul dedicat

Dacă vrei să păstrăm `CXFIFO / FIXISSUERESULT`, verifică existența sa:

```sql
SELECT MSGGROUP, MSGKEY, VALUE
FROM MAXMESSAGES
WHERE UPPER(MSGGROUP) = 'CXFIFO'
  AND UPPER(MSGKEY) = 'FIXISSUERESULT';
```

În Database Configuration → Messages, mesajul trebuie să aibă:


| Proprietate | Valoare |
| :-- | :-- |
| Message Group | Același grup folosit în script |
| Message Key | `FIXISSUERESULT` |
| Message Value | `{0}` |
| Display Method | Message Box, dacă proprietatea este disponibilă |

Folosește exact identificatorii salvați în configurație. Textul pus în „Descrierea evenimentului” din Application Designer nu creează un mesaj în catalogul Maximo.

Recomand acum varianta rapidă de la punctul 2. După verificarea datelor și corectarea mesajului, următoarea rulare va afișa motivul real al opririi sau confirmarea completă a salvării.

<span style="display:none">[^44_10][^44_11][^44_2][^44_3][^44_4][^44_5][^44_6][^44_7][^44_8][^44_9]</span>

<div align="center">⁂</div>

[^44_1]: image.jpg

[^44_2]: https://www.ibm.com/support/pages/ibm-maximo-application-suite-manage-component-patch-852

[^44_3]: https://www.ibm.com/support/pages/enabling-issues-transfers-application-maximo-75-fails

[^44_4]: https://www.ibm.com/support/pages/automation-scripts-skip-post‑sendmessage-code-ibm-maximo-when-communication-template-lacks-owner-dt450807

[^44_5]: https://www.ibm.com/support/pages/ibm-maximo-application-suite-manage-component-patch-851

[^44_6]: https://bportaluri.com/wp-content/MaximoListArchive/iuu94d8mqbegroups.com.html

[^44_7]: https://moremaximo.com/question/email-not-received-via-automation-script

[^44_8]: https://moremaximo.com/question/bmxzz7187e-labour-hours-must-be-greater-than-0

[^44_9]: https://ibm-maximo-dev.github.io/maximo-autoscript-documentation/otherlaunch/mxexception/

[^44_10]: https://community.ibm.com/community/user/discussion/maximo-mobile-maf-application-87-eam-no-data-or-apps

[^44_11]: https://moremaximo.com/question/automation-script-debug


---

# am implementat mesajul dedicat, acum primesc mesajul din pic1

Mesajul dedicat funcționează acum. Scriptul se oprește la verificarea de **coerență** dintre rândul din `CXSTOCURI` și tranzacția oficială `MATUSETRANS=209409`.[^45_1]

În versiunea 2.1, mesajul:

```text
Jurnal si sursa neconforme pentru RefID=209409
```

apare dacă diferă cel puțin una dintre următoarele:

- tipul din jurnal nu este `ISSUE`;
- `CXSTOCURI.CXQTY` diferă de `MATUSETRANS.QUANTITY`;
- `CXSTOCURI.UNITCOST` diferă de `MATUSETRANS.UNITCOST`;
- `CXSTOCURI.CXDOCUMENTDATE` diferă de `MATUSETRANS.ACTUALDATE`.

Această verificare este înaintea construirii tranzacției de salvare, deci rularea care s-a oprit aici nu a aplicat corecția.

## 1. Trebuie să vedem ce câmp diferă

În exporturile anterioare, cantitatea, prețul și data pentru `209409` coincideau între jurnal și sursă. Nu pot stabili din popup dacă datele s-au schimbat între timp sau dacă problema este reprezentarea datei în cod.[^45_2][^45_3]

Rulează acest SELECT pe datele actuale:

```sql
SELECT
    C.CXSTOCURIID,
    C.CXREFID,
    C.CXREF,
    M.ISSUETYPE,

    C.CXQTY       AS QTY_JURNAL,
    M.QUANTITY    AS QTY_SURSA,

    C.UNITCOST    AS PU_JURNAL,
    M.UNITCOST    AS PU_SURSA,

    C.CXDOCUMENTDATE,
    M.ACTUALDATE,

    CASE
        WHEN C.CXQTY IS NULL OR M.QUANTITY IS NULL
            THEN 'LIPSA'
        WHEN ABS(C.CXQTY - M.QUANTITY) <= 0.000001
            THEN 'OK'
        ELSE 'DIFERENTA'
    END AS CONTROL_CANTITATE,

    CASE
        WHEN C.UNITCOST IS NULL OR M.UNITCOST IS NULL
            THEN 'LIPSA'
        WHEN ABS(C.UNITCOST - M.UNITCOST) <= 0.0005
            THEN 'OK'
        ELSE 'DIFERENTA'
    END AS CONTROL_PRET,

    CASE
        WHEN C.CXDOCUMENTDATE IS NULL OR M.ACTUALDATE IS NULL
            THEN 'LIPSA'
        WHEN C.CXDOCUMENTDATE = M.ACTUALDATE
            THEN 'OK'
        ELSE 'DIFERENTA'
    END AS CONTROL_DATA

FROM CXSTOCURI C
LEFT JOIN MATUSETRANS M
    ON M.MATUSETRANSID = C.CXREFID

WHERE C.CXREFMBO = 'MATUSETRANS'
  AND C.CXREFID IN (209409, 209410)

ORDER BY C.CXREFID, C.CXSTOCURIID;
```

Nu modifica încă datele doar ca să treacă verificarea.

## 2. Îmbunătățim mesajul din script

Mesajul generic este insuficient — aici trebuie să afișăm exact diferența.

În `CXFIFOFIXISSUE`, caută blocul:

```python
for mem in members:
    r=jbyref[mem["id"]]
    if r["kind"]!="ISSUE" or differs(r["qty"],-mem["old_qty"]) or differs(r["cost"],mem["old_cost"],PRICE_EPS) or r["date"]!=mem["date"]:
        fail("Jurnal si sursa neconforme pentru RefID=%s" % mem["id"])
```

Înlocuiește-l cu:

```python
for mem in members:
    r = jbyref[mem["id"]]
    problems = []

    if r["kind"] != "ISSUE":
        problems.append(
            "tip jurnal=%s; asteptat ISSUE" % r["kind"]
        )

    if differs(r["qty"], -mem["old_qty"]):
        problems.append(
            "cantitate jurnal=%s; sursa=%s"
            % (text(r["qty"]), text(-mem["old_qty"]))
        )

    if differs(r["cost"], mem["old_cost"], PRICE_EPS):
        problems.append(
            "pret jurnal=%s; sursa=%s"
            % (text(r["cost"]), text(mem["old_cost"]))
        )

    if r["date"] != mem["date"]:
        problems.append(
            "data jurnal=[%s]; sursa=[%s]"
            % (text(r["date"]), text(mem["date"]))
        )

    if problems:
        fail(
            "Jurnal si sursa neconforme pentru RefID=%s: %s"
            % (mem["id"], "; ".join(problems))
        )
```

Această modificare nu relaxează protecția și nu schimbă logica de salvare; doar face diagnosticul explicit.

Dacă SELECT-ul arată toate controalele `OK`, dar scriptul raportează o diferență de dată, investigăm normalizarea datei în `datekey()`. Dacă SELECT-ul arată o diferență reală, trebuie verificată starea actuală a perechii înainte de continuarea corecției.

Trimite rezultatul SELECT-ului; dacă aplici și diagnosticul, trimite textul complet al noului mesaj.

<div align="center">⁂</div>

[^45_1]: image.jpg

[^45_2]: MATUSETRANS_202610301519.csv

[^45_3]: CXSTOCURI_202610301518.csv


---

# acesta e rezultatul selectului: cant si pret unitar diferite

409757209409ISSUEISSUE-3.000-2.0009.4109.4102026-07-19-00.00.00.0000002026-07-19-00.00.00.000000DIFERENTAOKOK
409758209410ISSUEISSUE-1.000-2.0009.4108.5202026-07-19-00.01.00.0000002026-07-19-00.01.00.000000DIFERENTADIFERENTAOK

Rezultatul confirmă cauza: `MATUSETRANS` are deja cantitățile și prețurile propuse pentru corecție, dar `CXSTOCURI` păstrează valorile vechi. Avem o stare de sincronizare **parțială** între sursă și jurnal.[^46_1]


| RefID | CXSTOCURI — acum | MATUSETRANS — acum |
| :-- | :-- | :-- |
| `209409` | `-3 × 9,410` | `-2 × 9,410` |
| `209410` | `-1 × 9,410` | `-2 × 8,520` |

Datele coincid, deci nu normalizarea datei provoacă oprirea.

Nu putem stabili doar din acest SELECT dacă modificarea sursei a venit dintr-o rulare anterioară a scriptului sau din altă intervenție. Rularea care afișează acum „Jurnal si sursa neconforme” se oprește înaintea scrierilor.

## Ce nu trebuie făcut

- Nu readucem automat `MATUSETRANS` la `-3 / -1` doar ca să treacă verificarea.
- Nu eliminăm verificarea de coerență.
- Nu aplicăm încă o dată corecția sursei.
- `Check FIFO` nu va sincroniza aceste obiecte: el verifică jurnalul, care încă are valorile vechi.

Trebuie verificat cât din operațiune a fost deja corectat, apoi aplicate numai modificările rămase.

## 1. Verificăm spliturile, valorile și documentul

Rulează:

```sql
SELECT
    M.MATUSETRANSID,
    M.QUANTITY             AS QTY_MATUSETRANS,
    M.QTYREQUESTED,
    M.CURBAL,
    M.UNITCOST             AS PU_MATUSETRANS,
    M.ACTUALCOST,
    M.LINECOST             AS VAL_MATUSETRANS,
    M.CURRENCYLINECOST,
    M.MATRECTRANSID         AS RECEPTIE_REFERITA,

    M.INVUSELINESPLITID,
    S.QUANTITY             AS QTY_SPLIT,
    S.UNITCOST             AS PU_SPLIT,

    M.INVUSELINEID,
    L.QUANTITY             AS QTY_LINIE,
    L.UNITCOST             AS PU_LINIE,
    L.LINECOST             AS VAL_LINIE,

    M.INVUSEID,
    H.INVUSENUM,
    H.CXTOTALCOST           AS VAL_DOCUMENT

FROM MATUSETRANS M

LEFT JOIN INVUSELINESPLIT S
    ON S.INVUSELINESPLITID = M.INVUSELINESPLITID

LEFT JOIN INVUSELINE L
    ON L.INVUSELINEID = M.INVUSELINEID

LEFT JOIN INVUSE H
    ON H.INVUSEID = M.INVUSEID

WHERE M.MATUSETRANSID IN (209409, 209410)

ORDER BY M.MATUSETRANSID;
```

Pentru o operațiune complet corectată în surse, ne așteptăm la:


| Element | Rezultat urmărit |
| :-- | :-- |
| `209409` | Cantitate `-2`, PU `9,410`, valoare `18,820`, sursă `1337464898` |
| `209410` | Cantitate `-2`, PU `8,520`, valoare `17,040`, sursă `1337462764` |
| Split `181769` | Cantitate `2`, PU `9,410` |
| Split `181770` | Cantitate `2`, PU `8,520` |
| Linia `164724` | Cantitate `4`, PU echivalent `8,965`, valoare `35,860` |
| Documentul | Total recalculat din toate liniile sale |

## 2. Verificăm dacă există istoricul scris de versiunea 2.1

Scriptul livrat adaugă istoricul în descrierea lungă a tranzacțiilor `MATUSETRANS`:

```sql
SELECT
    LDKEY,
    LDTEXT
FROM LONGDESCRIPTION
WHERE LDOWNERTABLE = 'MATUSETRANS'
  AND LDOWNERCOL = 'DESCRIPTION'
  AND LDKEY IN (209409, 209410)
ORDER BY LDKEY;
```

Dacă apare markerul:

```text
CXFIFO_ISSUE_FIX_V2
```

textul poate arăta ce valori a încercat să salveze acea versiune și când.

## Modificarea necesară în handler

`CXFIFOFIXISSUE` trebuie să distingă trei situații:

1. Sursa și jurnalul sunt încă în starea inițială → aplică întreaga corecție.
2. Sursa corespunde deja integral planului FIFO, dar jurnalul este vechi → sincronizează jurnalul și soldurile, fără să corecteze din nou sursa.
3. Sursa, spliturile și documentul sunt într-o stare mixtă → prezintă diferențele și aplică un plan de recuperare verificat, nu presupune că totul este corect.

Aici verificarea actuală a oprit corect o nouă aplicare, dar scriptului îi lipsește tratarea explicită a recuperării după o corecție parțială.

Trimite rezultatul primului SELECT și, dacă există, istoricul din al doilea. Acestea stabilesc dacă putem face doar sincronizarea `CXSTOCURI` sau trebuie completate și valorile/spliturile documentului.

<div align="center">⁂</div>

[^46_1]: image.jpg


---

# cred ca acum cateva zile am facut eu niste update-uri direct in baza, dar se pare ca nu-s complete. dar cu atat mai bine, scriptul nostru ar trebui sa corecteze si aceste situatii. uite rezultatul select-ului:

209409-2.0002.00012.0009.4109.41018.82018.82013374648981817692.0009.4101647244.0009.41037.640622566322435.860
209410-2.0002.00010.0008.5208.52017.04017.04013374627641817702.0008.5201647244.0009.41037.640622566322435.860

Da, acum situația este clară: intervențiile directe au corectat `MATUSETRANS`, spliturile și totalul documentului, dar nu au sincronizat toate reprezentările operațiunii.

Am adaptat scriptul pentru **recuperare** și am atașat varianta integrală `CXFIFOFIXISSUE 2.2-APPLY-RECOVERY-JAVA`, cu 675 de linii.

## Ce este deja corect și ce mai trebuie reparat

| Componentă | Stare actuală | Acțiunea necesară |
| :-- | :-- | :-- |
| `MATUSETRANS 209409` | -2 la 9,410; valoare 18,820 | Păstrează |
| `MATUSETRANS 209410` | -2 la 8,520; valoare 17,040 | Păstrează |
| Split `181769` | +2 la 9,410 | Păstrează |
| Split `181770` | +2 la 8,520 | Păstrează |
| `INVUSELINE 164724` | Cantitate 4; PU 9,410; valoare 37,640 | PU → 8,965; valoare → 35,860 |
| `INVUSE 62256` | Total 35,860 | Păstrează, dacă acesta este totalul tuturor liniilor |
| `CXSTOCURI 409757` | -3 la 9,410 | → -2 la 9,410; sold → 0 |
| `CXSTOCURI 409758` | -1 la 9,410 | → -2 la 8,520; sold → 10 |

Cantitățile, costurile, valorile și referințele de recepție din `MATUSETRANS` corespund deja planului discutat.[^47_1]

## Ce am schimbat în versiunea 2.2

### 1. Diferența dintre jurnal și sursă nu mai blochează automat recuperarea

Scriptul nu mai cere ca toate cantitățile și prețurile curente să fie identice înainte de corecție. Construiește planul FIFO și compară separat fiecare componentă cu rezultatul așteptat.

Păstrează însă controalele pentru identitatea operațiunii, direcție, date, articol, gestiune, splituri și cantitatea totală. Nu acceptă orice neconcordanță drept corectabilă automat.

### 2. Actualizează numai câmpurile care diferă

Cantitățile și prețurile deja corecte nu sunt reaplicate financiar. Scriptul completează modificările rămase în linie, document, splituri sau jurnal.

### 3. Recalculează totalul documentului în mod absolut

Nu mai folosește formula:

```text
Total curent document − valoare veche linie + valoare nouă linie
```

Aceasta ar fi greșită în cazul tău, deoarece totalul documentului este deja corect.

Noua formulă este:

```text
Total document =
suma valorilor celorlalte linii
+ valoarea corectă a liniei selectate
```

Astfel, pentru un document care conține doar această linie, totalul rămâne `35,860`, nu scade din nou.

### 4. Repetarea operațiunii nu adaugă o nouă corecție

Dacă toate componentele sunt deja conforme planului calculat, mesajul este:

```text
Operatiunea este deja conforma planului FIFO local; nimic modificat.
```


## Instalare și verificare

1. Păstrează o copie a scriptului actual.
2. Înlocuiește integral codul din `CXFIFOFIXISSUE` cu fișierul atașat.
3. Păstrează mesajul dedicat:

```text
CXFIFO / FIXISSUERESULT / {0}
```

4. Nu modifica butonul, launch point-ul sau protecția `CXADDTOCXSTOCURI`.
5. Testează întâi în TEST, pe operațiunea `209409 / 209410`, fără procese concurente care modifică inventarul sau jurnalul.
6. După salvare, rulează `Check FIFO` și verifică sursele, spliturile, linia și soldurile.

Scriptul nu conține `decimal`, `json`, `re` sau filtre de pilot. Nu modifică recepțiile, datele tranzacțiilor, `INVBALANCES` ori `INVLIFOFIFOCOST`.

Am verificat sintaxa și am testat offline cazul inițial `3 + 1`, cazul tău cu surse deja corectate `2 + 2`, totalul documentului deja corect și recalcularea repetată a soldurilor. Nu am executat integrarea MBO/Jython; aceasta trebuie validată în instanța de test înainte de folosirea operațională.

<div align="center">⁂</div>

[^47_1]: image.jpg


---

# acum primesc eroarea

BMXAA8229W - Înregistrarea MATUSETRANS : SITE=C02 ID de utilizare=209.409 a fost actualizată de un alt utilizator. Modificările dvs. nu au fost salvate. Actualizează înregistrarea și încearcă din nou.

Aceasta este o eroare de concurență pe **ROWSTAMP**: Maximo încearcă să salveze un `MATUSETRANS` folosind o versiune a rândului care nu mai corespunde celei din baza de date.

„Alt utilizator” nu înseamnă obligatoriu o altă persoană. Eroarea poate apărea și când aceeași înregistrare este încărcată prin două MBO-uri diferite și ambele încearcă să o actualizeze.[^48_1]

## În cazul nostru există o scriere inutilă pe 209409

În versiunea 2.2, chiar dacă datele financiare din `MATUSETRANS` sunt deja corecte, scriptul adaugă întotdeauna istoricul pe primul `MATUSETRANS`:

```python
first_member.setValue("DESCRIPTION_LONGDESCRIPTION", history, FLAGS)
first_member.setValue("HASLD", True, FLAGS)
```

Asta marchează `209409` ca modificat, deși pentru situația ta trebuie reparate în principal `INVUSELINE` și `CXSTOCURI`.

Această scriere trebuie eliminată din `MATUSETRANS`. Este o problemă a implementării pe care am livrat-o, nu un motiv să modifici manual `ROWSTAMP`.

Nu pot confirma doar din mesaj că aceasta este singura cauză; trebuie redusă și ambiguitatea salvării seturilor părinte/copil.

## 1. Mută istoricul corecției pe INVUSELINE

În script, caută:

```python
first_member=members[^48_0]["mbo"]
old_history=first_member.getString("DESCRIPTION_LONGDESCRIPTION")
history=old_history+("\n" if old_history else "")+audit_text
if len(history)>MAX_AUDIT:
    fail("Istoric de audit prea lung; nimic salvat")
```

Înlocuiește cu:

```python
audit_owner = line
old_history = audit_owner.getString("DESCRIPTION_LONGDESCRIPTION")
history = old_history + ("\n" if old_history else "") + audit_text

if len(history) > MAX_AUDIT:
    fail("Istoric de audit prea lung; nimic salvat")
```

Apoi caută:

```python
first_member.setValue("DESCRIPTION_LONGDESCRIPTION",history,FLAGS)
first_member.setValue("HASLD",True,FLAGS)
```

Înlocuiește cu:

```python
audit_owner.setValue("DESCRIPTION_LONGDESCRIPTION", history, FLAGS)
audit_owner.setValue("HASLD", True, FLAGS)
```

Astfel, istoricul rămâne persistent, dar nu mai forțăm actualizarea unui `MATUSETRANS` deja conform.

## 2. Înregistrează explicit în tranzacție numai seturile-rădăcină

Caută:

```python
tx=MXServer.getMXServer().createMXTransaction()
for ms in (docset,lineset,mset,sset,cxset):
    ms.setMXTransaction(tx)
    tx.add(ms)
```

Înlocuiește cu:

```python
tx = MXServer.getMXServer().createMXTransaction()

for ms in (docset, lineset, mset, sset, cxset):
    ms.setMXTransaction(tx)

tx.add(docset)
tx.add(cxset)
```

`lineset`, `mset` și `sset` sunt obținute prin relații din document. Păstrăm aceeași tranzacție, dar evităm să le înregistrăm explicit și ca rădăcini independente. Seturile obținute prin relații participă la salvarea părintelui.[^48_2][^48_3]

Aceasta este o corecție de structură a salvării, nu o dezactivare a verificării de concurență.

## 3. Adaugă temporar diagnosticul înainte de `tx.save()`

```python
for m in mts:
    service.log_error(
        "CXFIFOFIXISSUE PRE-SAVE: MATUSETRANSID=%s; modified=%s; rowstamp=%s"
        % (
            m.getLong("MATUSETRANSID"),
            text(m.isModified()),
            text(m.getRowStamp())
        )
    )
```

În cazul tău, dacă toate câmpurile planificate din cele două `MATUSETRANS` sunt deja corecte, după mutarea istoricului acestea ar trebui să apară nemodificate înainte de salvare.

Dacă apar totuși modificate, trebuie identificat ce câmp sau automatizare le marchează pentru actualizare.

## Înainte de următoarea încercare

1. Nu modifica `ROWSTAMP` și nu elimina protecția Maximo.
2. Verifică din nou starea surselor, spliturilor, liniei și jurnalului cu SELECT-urile folosite anterior.
3. Salvează modificările scriptului.
4. Închide și redeschide înregistrarea Inventory, pentru a elimina contextul UI vechi.
5. Testează o singură dată în TEST, fără alte intervenții pe aceleași date.

Dacă eroarea persistă, este necesar stack trace-ul complet din log în jurul `BMXAA8229W`, împreună cu liniile `CXFIFOFIXISSUE PRE-SAVE`. Popup-ul singur nu identifică a doua instanță MBO sau automatizarea care produce conflictul.

<span style="display:none">[^48_10][^48_11][^48_12][^48_13][^48_14][^48_15][^48_16][^48_17][^48_4][^48_5][^48_6][^48_7][^48_8][^48_9]</span>

<div align="center">⁂</div>

[^48_1]: https://www.interlocsolutions.com/blog/solving-record-has-been-updated-by-another-user.-refetch-and-try-again.-problems

[^48_2]: https://www.ibm.com/docs/en/masv-and-l/maximo-manage/cd?topic=scripts-scripting-best-practices

[^48_3]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/mbo/MboSet.html

[^48_4]: https://www.ibm.com/support/pages/apar/IV76966

[^48_5]: https://www.ibm.com/support/pages/maximo-asset-management-7612-interim-fix-020

[^48_6]: https://www.ibm.com/support/pages/updates-maximo-asset-management-761-feature-packs

[^48_7]: https://www.ibm.com/support/pages/updates-maximo-asset-management-760-feature-packs

[^48_8]: https://a3jgroup.com/afterduplicate-scripts/

[^48_9]: https://www.sharptree.io/blog/2023/2023-07-25-updated-by-another-user/

[^48_10]: https://community.ibm.com/community/user/discussion/ignore-certain-kinds-of-failed-integration-messages-dont-send-email-if-bmxaa8229w

[^48_11]: https://community.ibm.com/community/user/discussion/automation-script-for-duplicate-record-and-then-open-it-directly

[^48_12]: https://maximoinsights.com/2023/05/02/controlling-mbo-duplicate/

[^48_13]: https://ibm-maximo-dev.github.io/maximo-autoscript-documentation/objectscripts/duplicateobject/

[^48_14]: https://mygeekdaddy.net/2023/07/13/maximo-automation-script-on-duplicate-records/

[^48_15]: https://www.linkedin.com/pulse/maximo-customizations-just-fun-2-bulk-duplication-any-osama-alshahat-fzbjf

[^48_16]: https://moremaximo.com/discussion/bmxaa8229w-record-workorder-updated-by-another-user

[^48_17]: https://community.ibm.com/community/user/discussion/new-plussgeojson-columns-in-maximo-tables


---

# fyi nu am facut inca modificarile din mesajul anterior. tine cont ca din experienta anterioara de corectie fifo nu ar trebui sa incercam sa modificam si preturile/totalurile din invuse sau invuseline. asa ca da-mi modificarile la script tinand cont de lucrul asta

Am înțeles. Pornim de la versiunea 2.2 originală, fără modificările din mesajul anterior.

Noua delimitare este: scriem **numai** în `MATUSETRANS`, `INVUSELINESPLIT` și `CXSTOCURI`. `INVUSE` și `INVUSELINE` rămân obiecte de citire, pentru identificarea și validarea operațiunii.

Este o schimbare importantă și pentru salvare: nu este suficient să eliminăm cele trei actualizări de preț/total; trebuie să scoatem documentul și linia din tranzacția de scriere. În configurația ta există automatizări locale care actualizează linia și totalul documentului, deci evităm să le declanșăm prin modificarea acestor obiecte.[^49_1]

## 1. Marchează seturile citite prin `query()` ca NOSAVE

În interiorul funcției `execute()`, înlocuiește:

```python
def query(name,where,limit=MAX_ROWS):
    ms=open_set(user,name,where)
    opened.append(ms)
    return ms,rows(ms,limit)
```

cu:

```python
def query(name, where, limit=MAX_ROWS):
    ms = open_set(user, name, where)
    opened.append(ms)
    ms.setFlag(MboConstants.NOSAVE, True)
    return ms, rows(ms, limit)
```

Vom reactiva salvarea ulterior doar pentru seturile care au modificări planificate.

După:

```python
lineset=doc.getMboSet("INVUSELINE")
```

adaugă:

```python
lineset.setFlag(MboConstants.NOSAVE, True)
```


## 2. Deschide consumurile și spliturile independent de INVUSELINE

Înlocuiește:

```python
mset=line.getMboSet(
    "$CXFIFO_FIX_MEMBERS",
    "MATUSETRANS",
    "INVUSEID=%s AND INVUSELINEID=%s" % (invuseid,lineid)
)
mts=rows(mset,MAX_SPLITS)
```

cu:

```python
mset, mts = query(
    "MATUSETRANS",
    "INVUSEID=%s AND INVUSELINEID=%s" % (invuseid, lineid),
    MAX_SPLITS
)
```

Înlocuiește:

```python
sset=line.getMboSet(
    "$CXFIFO_FIX_SPLITS",
    "INVUSELINESPLIT",
    "INVUSELINEID=%s" % lineid
)
sr=rows(sset,MAX_SPLITS)
```

cu:

```python
sset, sr = query(
    "INVUSELINESPLIT",
    "INVUSELINEID=%s" % lineid,
    MAX_SPLITS
)
```

Astfel, seturile pe care le corectăm nu mai sunt încărcate ca descendenți ai liniei de document.

## 3. Elimină actualizările liniei și documentului

Șterge aceste trei instrucțiuni:

```python
plan_number(line,"UNITCOST",new_unit)
plan_number(line,"LINECOST",new_total)
plan_number(doc,"CXTOTALCOST",new_doc_total)
```

Șterge și calculele care nu mai sunt necesare:

```python
new_unit=money(new_total/total)
```

și instrucțiunea care începe cu:

```python
new_doc_total=desired_header_total(
```

Funcția `desired_header_total()` poate fi eliminată integral, deoarece nu o mai folosim.

Păstrează calculul:

```python
new_total=sum((a["value"] for a in mapped),ZERO)
```

Acesta reprezintă valoarea operațiunii corectate și este folosit în mesaj, nu pentru actualizarea documentului.

## 4. Nu mai scrie istoricul pe MATUSETRANS sau pe document

Din versiunea 2.2 șterge blocul:

```python
first_member=members[^49_0]["mbo"]
old_history=first_member.getString("DESCRIPTION_LONGDESCRIPTION")
history=old_history+("\n" if old_history else "")+audit_text
if len(history)>MAX_AUDIT:
    fail("Istoric de audit prea lung; nimic salvat")
```

Șterge și:

```python
first_member.setValue("DESCRIPTION_LONGDESCRIPTION",history,FLAGS)
first_member.setValue("HASLD",True,FLAGS)
```

Nu le înlocui cu scrieri pe `INVUSELINE`, așa cum propusesem anterior.

Păstrează `audit_text` și înregistrarea lui în log. Pentru această variantă, setează nivelul de jurnal al scriptului la `INFO` și verifică în TEST că se înregistrează valorile înainte/după. Nu vom folosi descrierile documentelor doar ca să păstrăm auditul tehnic.

## 5. Include în tranzacție doar seturile efectiv modificate

Înlocuiește blocul:

```python
tx=MXServer.getMXServer().createMXTransaction()
for ms in (docset,lineset,mset,sset,cxset):
    ms.setMXTransaction(tx)
    tx.add(ms)
```

cu:

```python
allowed_tables = (
    "MATUSETRANS",
    "INVUSELINESPLIT",
    "CXSTOCURI"
)

planned_tables = set(
    m.getName().upper()
    for m, f, kind, v, old in plans
)

unexpected = planned_tables.difference(set(allowed_tables))

if unexpected:
    fail(
        "Planul contine obiecte nepermise pentru scriere: "
        + ", ".join(sorted(unexpected))
    )

tx = MXServer.getMXServer().createMXTransaction()

for name, ms in (
    ("MATUSETRANS", mset),
    ("INVUSELINESPLIT", sset),
    ("CXSTOCURI", cxset)
):
    if name in planned_tables:
        ms.setFlag(MboConstants.NOSAVE, False)
        ms.setMXTransaction(tx)
        tx.add(ms)
```

În situația ta, dacă `MATUSETRANS` și spliturile sunt deja conforme, acestea nu vor mai fi înscrise de script în tranzacția de scriere doar pentru istoric. Planul poate conține exclusiv actualizările `CXSTOCURI` rămase.

## 6. Elimină verificarea care cere corectarea totalurilor

După `tx.save()`, șterge:

```python
if different(number(line,"LINECOST"),new_total) or different(number(doc,"CXTOTALCOST"),new_doc_total):
    fail("Totaluri suprascrise la salvare; rollback")
```

Păstrează verificarea fiecărui câmp din `plans`:

```python
for m,f,kind,v,old in plans:
    if (
        kind=="NUMBER" and different(number(m,f),v)
    ) or (
        kind=="ID" and m.getLong(f)!=v
    ):
        fail(
            "Logica de salvare a suprascris planul pe %s.%s; rollback"
            % (m.getName(),f)
        )
```


## Rezultatul urmărit

| Obiect | Comportament |
| :-- | :-- |
| `MATUSETRANS` | Actualizat numai dacă există câmpuri neconforme cu planul |
| `INVUSELINESPLIT` | Cantitate și preț sincronizate, dacă este necesar |
| `CXSTOCURI` | Cantități, prețuri și solduri afectate |
| `INVUSELINE` | Citire; fără actualizarea PU, valorii, descrierii sau altor câmpuri |
| `INVUSE` | Citire; fără recalcularea totalului sau schimbarea statusului |
| `INVBALANCES` / `INVLIFOFIFOCOST` | Fără actualizări explicite |

Consecința acceptată a acestei delimitări: `INVUSELINE` poate păstra `UNITCOST=9,410` și `LINECOST=37,640`, chiar dacă tranzacțiile de consum însumează `35,860`. Scriptul nu va mai încerca să elimine această diferență și nu va declara documentul financiar complet reconciliat.

Aceste modificări reduc implicarea MBO-urilor de document în salvare, dar nu demonstrează singure că eroarea `BMXAA8229W` este rezolvată. Testează după redeschiderea înregistrării; dacă persistă, trebuie urmărit stack trace-ul pentru a identifica instanța sau automatizarea care actualizează suplimentar `MATUSETRANS`. Nu modificăm manual `ROWSTAMP`.

<div align="center">⁂</div>

[^49_1]: AUTOSCRIPT_202610301531.csv


---

# Ok, e prea mult de modificat. Da-mi scriptul cap coada

Am atașat scriptul **complet** `CXFIFOFIXISSUE`, versiunea `2.3-TRANSACTIONS-ONLY-JAVA`, cu 682 de linii. Înlocuiește integral versiunea 2.2; nu mai aplica separat modificările din mesajele anterioare.

## Ce am schimbat

| Obiect | Comportament |
| :-- | :-- |
| `MATUSETRANS` | Actualizat numai dacă există diferențe reale față de plan |
| `INVUSELINESPLIT` | Cantitate și preț sincronizate, dacă este necesar |
| `CXSTOCURI` | Cantități, prețuri și solduri afectate |
| `INVUSE` | Numai citire; fără actualizarea totalului sau statusului |
| `INVUSELINE` | Numai citire; fără actualizarea prețului, valorii sau descrierii |
| `INVBALANCES` / `INVLIFOFIFOCOST` | Fără actualizări explicite |

Am eliminat și scrierea istoricului pe `MATUSETRANS`. Planul înainte/după și confirmarea commitului sunt înregistrate în log, fără să marcăm drept modificată o sursă deja conformă.

Seturile pentru consumuri și splituri sunt deschise independent de document. În tranzacția de salvare intră numai seturile cu modificări reale; celelalte rămân `NOSAVE`.

## Pentru starea actuală a perechii tale

Datele transmise arată că `MATUSETRANS` și spliturile au deja distribuția corectă `2 + 2`.[^50_1]

În testul numeric pentru această stare, noua versiune nu planifică scrieri în `MATUSETRANS`. Completează corecțiile rămase în jurnal:

```text
409757 / RefID 209409:
CXQTY=-2; UNITCOST=9,410; CXCURBAL=0

409758 / RefID 209410:
CXQTY=-2; UNITCOST=8,520; CXCURBAL=10
```

Sunt recalculate și soldurile ulterioare afectate, inclusiv cele lipsă.

`INVUSELINE` poate păstra intenționat prețul și valoarea veche. Scriptul nu mai încearcă să le corecteze și nu declară documentul financiar complet reconciliat.

## Instalare

1. Păstrează o copie a codului actual.
2. Deschide Automation Scripts → `CXFIFOFIXISSUE`.
3. Înlocuiește tot conținutul cu fișierul atașat.
4. Setează nivelul de jurnal la `INFO` pentru testare și trasabilitate.
5. Păstrează butonul, launch point-ul și mesajul dedicat:

```text
CXFIFO / FIXISSUERESULT / {0}
```

6. Redeschide înregistrarea Inventory și testează o singură execuție în TEST, fără procese concurente.
7. După salvare, rulează `Check FIFO`.

Scriptul nu folosește `decimal`, `json` sau `re` și nu are restricții de pilot.

Am verificat sintaxa, planul de recuperare și faptul că, pentru cazul tău, setul de scriere este doar `CXSTOCURI`. Nu am executat integrarea în Maximo/Jython. Modificările reduc implicarea inutilă a surselor și documentelor în salvare, dar rezolvarea erorii `BMXAA8229W` trebuie confirmată în instanță. Dacă o automatizare modifică indirect stocul sau documentele, controlul post-commit afișează o avertizare; aceasta trebuie investigată înaintea următoarei corecții.

<div align="center">⁂</div>

[^50_1]: image.jpg


---

# ok, cele 2 linii au fost corectate, acum cand trec la 209419 primesc aceasta eroare

Prima pereche a fost sincronizată corect: în captură, `209409` este acum `-2 × 9,410`, iar `209410` este `-2 × 8,520`, ambele cu `BADFIFO=N`.[^51_1]

La `209419` apare însă un alt conflict de **ROWSTAMP**, de această dată pe `INVUSELINESPLIT`, nu pe `MATUSETRANS`.

## 1. Ce înregistrare este în conflict

`CONTENTUID` din mesaj:

```text
f49f07eb-5d08-4ee4-b237-b12683faa52d
```

corespunde splitului `181786`, asociat consumului `209419`. Acesta avea cantitatea `4` și prețul `9,410`.[^51_2][^51_3]

Corecția urmărită pentru această operațiune este:

```text
MATUSETRANS 209419:
QUANTITY = -4
UNITCOST = 8,520
LINECOST = 34,080

INVUSELINESPLIT 181786:
QUANTITY = 4
UNITCOST = 8,520
```


## 2. De ce prima operațiune a mers, iar aceasta nu

La prima pereche, sursele și spliturile erau deja corectate prin intervențiile anterioare. Scriptul a avut de sincronizat jurnalul.

La `209419`, trebuie modificate efectiv atât `MATUSETRANS`, cât și splitul oficial. Aici intră în joc logica de salvare a obiectelor înrudite: `MatUseTrans.save()` salvează și obiecte legate, nu doar rândul principal.[^51_4]

Cea mai probabilă cauză este că același split este implicat în salvare prin două instanțe MBO:

- instanța încărcată separat de script;
- o instanță accesată prin relația tranzacției-sursă.

Acesta este un mecanism cunoscut pentru erorile „updated by another user”, chiar fără alt utilizator conectat. Nu pot confirma însă calea exactă fără stack trace-ul complet.[^51_5]

## 3. Ce trebuie schimbat în script

Nu trebuie să revenim la modificarea `INVUSE` sau `INVUSELINE`. Acestea rămân numai pentru citire.

Schimbarea necesară este la încărcarea și salvarea spliturilor:

1. `MATUSETRANS` rămâne setul-rădăcină al operațiunii.
2. Fiecare split de scriere este obținut prin relația standard:

```python
m.getMboSet("INVUSELINESPLIT")
```

3. Verificăm că relația întoarce exact splitul indicat de `INVUSELINESPLITID`.
4. Folosim acea instanță pentru actualizare.
5. Nu mai înscriem un set-rădăcină independent `INVUSELINESPLIT` în tranzacția de salvare.
6. Salvăm rădăcina `MATUSETRANS`, cu spliturile sale, împreună cu `CXSTOCURI`.

Relația `MATUSETRANS → INVUSELINESPLIT` există în configurația exportată și este definită prin `invuselinesplitid=:invuselinesplitid`.[^51_6]

Scopul este să avem o singură instanță de scriere pentru fiecare split. Nu să ignorăm verificarea `ROWSTAMP` și nici să facem două commituri separate.

## 4. Verificăm starea după eroare înainte de o nouă încercare

Rulează acest SELECT:

```sql
SELECT
    M.MATUSETRANSID,
    M.QUANTITY,
    M.UNITCOST,
    M.ACTUALCOST,
    M.LINECOST,
    M.MATRECTRANSID,

    S.INVUSELINESPLITID,
    S.CONTENTUID,
    S.QUANTITY AS QTY_SPLIT,
    S.UNITCOST AS PU_SPLIT,

    C.CXSTOCURIID,
    C.CXQTY,
    C.UNITCOST AS PU_JURNAL,
    C.CXCURBAL

FROM MATUSETRANS M

LEFT JOIN INVUSELINESPLIT S
    ON S.INVUSELINESPLITID = M.INVUSELINESPLITID

LEFT JOIN CXSTOCURI C
    ON C.CXREFMBO = 'MATUSETRANS'
   AND C.CXREFID = M.MATUSETRANSID

WHERE M.MATUSETRANSID = 209419;
```

Nu apăsa repetat butonul până nu verificăm dacă toate valorile au rămas vechi sau există din nou o stare parțială. Păstrăm prima pereche deja corectată; nu este necesar să o anulăm.

Următoarea revizie trebuie să corecteze această structură de încărcare a spliturilor, nu să adauge un retry automat sau să forțeze salvarea peste `ROWSTAMP`.

<span style="display:none">[^51_10][^51_11][^51_12][^51_13][^51_14][^51_15][^51_16][^51_17][^51_18][^51_19][^51_20][^51_21][^51_7][^51_8][^51_9]</span>

<div align="center">⁂</div>

[^51_1]: image.jpg

[^51_2]: INVUSELINESPLIT_202610301530.csv

[^51_3]: MATUSETRANS_202610301519.csv

[^51_4]: https://bportaluri.com/wp-content/MaximoJavaDocs7612/psdi/app/inventory/MatUseTrans.html

[^51_5]: https://www.interlocsolutions.com/blog/solving-record-has-been-updated-by-another-user.-refetch-and-try-again.-problems

[^51_6]: MAXRELATIONSHIP_202610301521.csv

[^51_7]: https://gao.az.gov/sites/default/files/2022-05/MAXIM_MAXIMO_Inventory%2520Management_PG_v4_0.pdf

[^51_8]: https://maximosecrets.com/2020/06/29/issues-and-returns-in-inventory-usage/

[^51_9]: https://www.ibm.com/support/pages/apar/IV33446

[^51_10]: https://maximosecrets.com/2020/06/18/financial-processes-in-inventory-7-of-8/

[^51_11]: https://bportaluri.com/wp-content/MaximoJavaDocs7612/psdi/app/inventory/InvUseLine.html

[^51_12]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/app/inventory/virtual/package-summary.html

[^51_13]: https://bportaluri.com/wp-content/MaximoJavaDocs7612/psdi/app/inventory/InvUse.html

[^51_14]: https://bportaluri.com/wp-content/MaximoJavaDocs7612/psdi/app/inventory/FldMatUseTransQuantity.html

[^51_15]: https://moremaximo.com/discussion/issue-with-quantity-default-value-in-matusetrans

[^51_16]: https://maximosecrets.com/2020/07/03/a-summary-of-the-financial-processes-in-inventory-usage/

[^51_17]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/app/inventory/MatUseTrans.html

[^51_18]: https://bportaluri.com/wp-content/MaximoJavaDocs76/psdi/app/inventory/InvTrans.html

[^51_19]: https://www.linkedin.com/posts/sachinkrgupta-maximo-consultant_hi-ibm-maximo-team-once-again-i-have-brought-activity-7349437698945814528-pZUu

[^51_20]: https://maximodeploy.blogspot.com/2015/11/inventory-issue-and-return-transactions.html

[^51_21]: https://community.spiceworks.com/t/create-a-report-for-transaction-item-in-maximo/941028


---

# asta e rezultatul

209419-4.0008.5208.52034.0801337462764181786f49f07eb-5d08-4ee4-b237-b12683faa52d4.0009.410409767-4.0009.410-4.000

Rezultatul confirmă încă o stare **parțială**: câmpurile principale din `MATUSETRANS 209419` au valorile corecte, dar splitul și jurnalul au rămas la prețul vechi.[^52_1]

## Starea actuală și corecția rămasă

| Obiect | Stare actuală | Rezultat urmărit |
| :-- | :-- | :-- |
| `MATUSETRANS 209419` | `-4` la `8,520`; valoare `34,080`; sursă `1337462764` | Păstrarea câmpurilor deja conforme |
| `INVUSELINESPLIT 181786` | `+4` la `9,410` | `+4` la `8,520` |
| `CXSTOCURI 409767` | `-4` la `9,410`; sold `-4` | `-4` la `8,520`; sold `6` |

Soldul `6` rezultă din cele `10` unități rămase la `8,520` după prima operațiune corectată, minus consumul de `4`.

Nu trebuie să anulăm prima pereche și nici să revenim cu prețul lui `209419` la `9,410`.

## Ce înseamnă pentru script

Problema nu mai este calculul FIFO. Problema este coordonarea salvării obiectelor înrudite.

Faptul că vezi acum sursa corectată, în timp ce splitul este vechi, arată că nu putem considera operațiunea complet salvată sau complet anulată. Totuși, acest SELECT singur nu dovedește în ce rulare au fost schimbate câmpurile sursei sau cine a făcut salvarea.

Trebuie corectată structura handlerului astfel încât:

1. Să recalculeze planul și să recunoască valorile deja corecte.
2. Să nu mai rescrie inutil câmpurile conforme din `MATUSETRANS`.
3. Să folosească pentru split o singură instanță de scriere, accesată prin relația `MATUSETRANS → INVUSELINESPLIT`.
4. Să nu salveze același split și printr-un set-rădăcină independent.
5. Să păstreze `INVUSE` și `INVUSELINE` numai pentru citire.
6. Să verifice rezultatul efectiv după salvare, nu doar valorile MBO din memorie.

Relația standard necesară există în exportul tău. Folosirea simultană a unor instanțe MBO diferite pentru același rând este o cauză cunoscută a conflictelor de acest tip, dar trebuie confirmată în log pentru rularea concretă.[^52_2][^52_3]

## Nu recomand încă o apăsare „ca să completeze restul”

Este posibil ca o nouă rulare să construiască acum un plan mai mic, doar pentru split și jurnal. Dar nu vreau să folosim repetarea operațiunii ca substitut pentru repararea mecanismului de salvare.

În plus, controlul post-commit al versiunii actuale nu este suficient pentru un caz oprit prin excepție înainte să ajungă la acel control.

## Ce mai este necesar pentru remedierea tehnică

Nu mai am nevoie de alte extrase pentru a stabili cantitatea, prețul și soldul corect al acestei operațiuni.

Am nevoie de stack trace-ul complet din log pentru `BMXAA8229W`, din momentul apăsării pe `209419`, împreună cu liniile:

```text
CXFIFOFIXISSUE PLAN
```

Acestea trebuie să arate dacă în rularea respectivă erau planificate scrieri atât pe `MATUSETRANS`, cât și pe `INVUSELINESPLIT`, și unde apare conflictul în salvare. Nu modifica manual `ROWSTAMP` și nu elimina sincronizarea splitului ca să dispară eroarea. Până la identificarea căii de salvare, oprește corecțiile pe alte linii și păstrează această stare pentru diagnostic.

<div align="center">⁂</div>

[^52_1]: image.jpg

[^52_2]: MAXRELATIONSHIP_202610301521.csv

[^52_3]: https://www.interlocsolutions.com/blog/solving-record-has-been-updated-by-another-user.-refetch-and-try-again.-problems


---

# ok, suna bine, da-mi scriptul cap coada. daca e mai simplu hai sa eliminam modificarile din invuselinesplit pt moment

Am atașat scriptul **complet** `CXFIFOFIXISSUE`, versiunea `2.4-MATUSETRANS-CXSTOCURI-JAVA`, cu 666 de linii.

Această versiune elimină actualizările explicite în `INVUSELINESPLIT`, conform cerinței tale.

## Domeniul de scriere

| Obiect | Comportament |
| :-- | :-- |
| `MATUSETRANS` | Corectează numai câmpurile care diferă de plan |
| `CXSTOCURI` | Sincronizează cantitățile, prețurile și soldurile afectate |
| `INVUSELINESPLIT` | Fără actualizări explicite; doar control informativ |
| `INVUSE` / `INVUSELINE` | Numai citire; fără modificarea prețurilor, totalurilor sau descrierilor |
| `MATRECTRANS` | Numai citire pentru verificarea intrărilor folosite |
| `INVBALANCES` / `INVLIFOFIFOCOST` | Fără actualizări explicite |

Lista obiectelor permise la scriere este verificată înaintea salvării. Seturile care nu au modificări reale nu intră în tranzacția de scriere.

## Pentru cazul actual — 209419

Rezultatul transmis arată că principalele câmpuri din `MATUSETRANS` sunt deja corecte, în timp ce splitul și jurnalul păstrează prețul vechi.[^53_1]

Noua versiune urmărește:


| Componentă | Rezultat |
| :-- | :-- |
| `MATUSETRANS 209419` | Păstrează câmpurile deja conforme: `-4`, PU `8,520`, valoare `34,080`, sursă `1337462764` |
| `CXSTOCURI 409767` | `CXQTY=-4`, `UNITCOST=8,520`, `CXCURBAL=6` |
| `INVUSELINESPLIT 181786` | Nu îl corectează explicit; poate rămâne la PU `9,410` |

Dacă și celelalte câmpuri `MATUSETRANS` sunt conforme, scriptul va avea de scris numai în `CXSTOCURI`.

## Limitarea este afișată explicit

Mesajul de succes începe cu:

```text
SALVAT LIMITAT:
```

și precizează că spliturile, documentele și straturile oficiale nu au fost reconciliate.

După rularea `Check FIFO`, `209419` poate primi `BADFIFO=N` în auditul local. Acest rezultat nu confirmă că `INVUSELINESPLIT` are și el prețul corect.

Am păstrat și controlul informativ după commit: dacă un split se schimbă indirect prin logica nativă sau prin alte automatizări, mesajul semnalează acest lucru. Eliminarea scrierilor explicite nu poate garanta absența tuturor efectelor native.

## Instalare

1. Păstrează o copie a versiunii curente.
2. În Automation Scripts → `CXFIFOFIXISSUE`, înlocuiește integral codul cu fișierul atașat.
3. Păstrează butonul, launch point-ul și mesajul:

```text
CXFIFO / FIXISSUERESULT / {0}
```

4. Setează nivelul de jurnal la `INFO`.
5. Redeschide înregistrarea Inventory și testează o singură execuție pe `209419`, în TEST și fără procese concurente.
6. Verifică rezultatul în DB, apoi rulează `Check FIFO`.

Scriptul nu folosește `decimal`, `json` sau `re`, nu scrie manual `ROWSTAMP` și nu are filtre de pilot.

Am verificat sintaxa și am testat offline planul pentru `209419`: `-4 × 8,520`, valoare `34,080`, sold de jurnal `6`. Nu am executat integrarea MBO/Jython și nu pot confirma încă dispariția conflictului în instanța ta. Dacă reapare, nu forța repetarea salvării; stack trace-ul va fi necesar pentru identificarea căii native care mai actualizează înregistrarea.

<div align="center">⁂</div>

[^53_1]: image.jpg


---

# ok, suna bine, da-mi scriptul cap coada; as propune pt acest moment sa eliminam updateurile de la INVUSELINESPLIT. Aceste cantitati si valori nu impacteaza tranzactiile viitoare. ce zici?

Am atașat scriptul **complet** `CXFIFOFIXISSUE`, versiunea `2.4-MATUSETRANS-CXSTOCURI-ONLY`, cu 672 de linii. Înlocuiește integral versiunea anterioară.

Am eliminat actualizările explicite și setul de salvare independent pentru `INVUSELINESPLIT`.

## Domeniul acestei versiuni

| Obiect | Comportament |
| :-- | :-- |
| `MATUSETRANS` | Corectează numai câmpurile neconforme cu planul FIFO |
| `CXSTOCURI` | Sincronizează cantitatea, prețul și soldurile afectate |
| `INVUSELINESPLIT` | Fără actualizări explicite; citire doar pentru controlul post-salvare |
| `INVUSE` / `INVUSELINE` | Numai citire |
| Recepții `MATRECTRANS` | Numai citire pentru validarea provenienței |
| `INVBALANCES` / `INVLIFOFIFOCOST` | Fără actualizări explicite |

Nu mai există un set `INVUSELINESPLIT` înscris de script în tranzacția de scriere. Lista obiectelor permise pentru scriere este limitată la:

```python
WRITE_TABLES = ("MATUSETRANS", "CXSTOCURI")
```


## Precizarea privind impactul spliturilor

Pentru calculul nostru FIFO local, `INVUSELINESPLIT` nu este sursa de calcul. Putem deci continua această etapă fără să îl sincronizăm.

Totuși, nu pot confirma că spliturile nu au impact în toate fluxurile Maximo: ele participă la procesarea Inventory Usage și la generarea tranzacțiilor. Această versiune lasă intenționat documentele și spliturile nereconciliate. Nu trebuie considerate complet corectate pentru reprocesare sau alte fluxuri fără verificare separată.[^54_1]

## Rezultatul urmărit acum pentru 209419

Dacă restul câmpurilor sursei sunt deja conforme, scriptul nu le mai rescrie. Completează jurnalul:

```text
CXSTOCURIID = 409767
CXREFID     = 209419
CXQTY       = -4
UNITCOST    = 8,520
CXCURBAL    = 6
```

Sursa FIFO rămâne recepția `1337462764`, iar valoarea consumului este `34,080`.

Splitul `181786` poate rămâne la `9,410`, conform delimitării solicitate.

## Instalare

1. Păstrează o copie a scriptului actual.
2. Înlocuiește tot conținutul din `CXFIFOFIXISSUE` cu fișierul atașat.
3. Păstrează protecția `CXADDTOCXSTOCURI`.
4. Setează nivelul de jurnal la `INFO` pentru trasabilitate.
5. Păstrează mesajul:

```text
CXFIFO / FIXISSUERESULT / {0}
```

6. Redeschide înregistrarea Inventory și testează o singură apăsare pe `209419` în TEST, fără procese concurente.
7. După salvare, rulează `Check FIFO`.

## Verificări și limite

Am verificat sintaxa și am testat numeric cele patru operațiuni din exporturi, inclusiv recuperarea după corecții parțiale. Scriptul nu folosește `decimal`, `json`, `re` sau filtre de pilot.

Nu am executat integrarea în Maximo/Jython și nu pot garanta că logica nativă de salvare nu va modifica indirect un obiect înrudit. De aceea, controlul post-commit compară și spliturile înainte/după. Dacă apare o avertizare că au fost modificate indirect sau reapare `BMXAA8229W`, oprește corecțiile următoare și păstrează logul; nu forța salvarea și nu modifica `ROWSTAMP`.

<span style="display:none">[^54_10][^54_11][^54_12][^54_13][^54_14][^54_15][^54_2][^54_3][^54_4][^54_5][^54_6][^54_7][^54_8][^54_9]</span>

<div align="center">⁂</div>

[^54_1]: https://www.ibm.com/support/pages/split-usage-quantity-inventory-usage-application

[^54_2]: https://www.ibm.com/support/pages/apar/IJ47652

[^54_3]: https://www.ibm.com/docs/en/maximo-manage/cd?topic=records-split-usage-quantity-feature

[^54_4]: https://www.ibm.com/support/pages/ibm-maximo-mro-inventory-optimization-how-forecast-usage-value-calculated

[^54_5]: https://www.ibm.com/docs/en/maximo-manage/cd?topic=inventory-picking-staging

[^54_6]: https://www.ibm.com/docs/en/maximo-manage/cd?topic=usage-inventory-records

[^54_7]: https://www.ibm.com/docs/en/maximo-manage/cd?topic=inventory-splitting-quantity-usage-line

[^54_8]: https://www.ibm.com/docs/en/maximo-manage/cd?topic=properties-inventory-property

[^54_9]: https://www.ibm.com/support/pages/unable-issue-stocked-tools

[^54_10]: https://www.ibm.com/support/pages/apar/IJ30006

[^54_11]: https://www.ibm.com/support/pages/transferring-100-items-13-conversion-should-not-mean-you-receive-99-back-0

[^54_12]: https://www.ibm.com/support/pages/apar/IJ17509

[^54_13]: https://help.sap.com/doc/47ffac0b8ea04ec084e477c87a98825d/8.1/en-US/MxIM81_UserGuideWindows.pdf

[^54_14]: https://www.ibm.com/mysupport/aCI3p0000008WeL?DT244688

[^54_15]: https://www.scribd.com/document/293803595/User-Guide-for-Material-Managment-in-MAXIMO-docx


---

# am reusit sa fac modif fifo astfel: apas Bine pe eroare, fac refresh la pagina, apas pe Check Fifo si apoi vad modificarile efectuate. Cred ca aici ar trebui sa fie implementata o imbunatatire. Daca ti-e util pot sa mai includ si un al 3lea buton.

2\. in pic2 e noul mesaj pt corectia fifo cu matusetransid 222539

Da, sunt două probleme **distincte**: rezultatul salvării/refresh-ului și protecția întâlnită la `222539`.

## 1. Nu trebuie să fie necesar refresh manual după o eroare

În a doua captură, jurnalul din iulie arată alocările corectate, inclusiv soldurile `10 → 6 → 3 → 2 → 0` la `8,520`. Asta confirmă coerența locală a secvenței afișate.[^55_1]

Totuși, nu trebuie să tratăm `BMXAA8229W` ca pe un mesaj benign pe care utilizatorul îl închide ca să continue. Dacă după eroare găsim modificări persistate, trebuie verificat ce componente au fost salvate; refresh-ul nu repară coordonarea salvării.

### Îmbunătățirea recomandată pentru butonul 2

Fluxul ar trebui să devină:

```text
Calculează planul
    ↓
Aplică modificările
    ↓
Recitește din DB toate câmpurile planificate
    ↓
Clasifică rezultatul
    ↓
Reauditează jurnalul și reîncarcă tabelul
    ↓
Afișează rezultatul real
```

Mesajele trebuie să distingă explicit:


| Stare verificată | Mesaj |
| :-- | :-- |
| Toate modificările așteptate sunt persistate | `CORECTIE APLICATA SI VERIFICATA` |
| Numai o parte este persistată | `CORECTIE PARTIALA — nu continua pe alta operatiune` |
| Nicio modificare așteptată nu este persistată | `CORECTIE NEAPLICATA` |
| Nu putem reciti/verifica datele | `REZULTAT NECONFIRMAT — verifica in DB inainte de repetare` |

Nu vom converti automat o excepție în succes doar fiindcă unele prețuri au devenit corecte.

### Este necesar un al treilea buton?

Nu pentru a rezolva această problemă. Prefer să includem refresh-ul și reverificarea în butonul 2.

Un al treilea buton poate fi util opțional ca „Reîncarcă și verifică”, fără corecții financiare. Dar nu ar trebui să fie obligatoriu după fiecare intervenție.

Pentru reauditearea automată trebuie reutilizat motorul auditului fără popup-ul său final, nu invocat orbește întregul `CXINVAUDIT`: acesta are propriul context `INVENTORY` și termină acțiunea prin `service.error()`.

## 2. Mesajul pentru 222539 este o oprire controlată

Textul:

```text
Sursa transmisa/legata/returnata; corectie automata refuzata
```

provine din protecția introdusă în script. Nu indică neapărat o eroare tehnică.[^55_1]

În versiunea actuală, apare dacă unul dintre rândurile operațiunii are:

```text
CXSENTEBS = True
sau FINCNTRLID completat
sau ISSUEID completat
sau QTYRETURNED diferit de zero
```

Mesajul este prea generic. Îl vom modifica să arate condiția exactă și `MATUSETRANSID` care a declanșat-o.

În captură există și tranzacții `RETURN`, deci un consum cu cantitate returnată este o explicație posibilă, dar nu putem atribui acel retur lui `222539` doar după poziția din tabel.

## 3. Select-urile pentru identificarea protecției

### A. Operațiunea selectată și toate rândurile liniei sale

```sql
WITH LINIA AS (
    SELECT INVUSEID, INVUSELINEID
    FROM MATUSETRANS
    WHERE MATUSETRANSID = 222539
)
SELECT
    M.MATUSETRANSID,
    M.ISSUETYPE,
    M.ACTUALDATE,
    M.QUANTITY,
    M.UNITCOST,
    M.ACTUALCOST,
    M.LINECOST,
    M.INVUSEID,
    M.INVUSELINEID,
    M.INVUSELINESPLITID,
    M.CXSENTEBS,
    M.FINCNTRLID,
    M.ISSUEID,
    M.QTYRETURNED
FROM MATUSETRANS M
WHERE M.MATUSETRANSID = 222539
   OR EXISTS (
       SELECT 1
       FROM LINIA L
       WHERE L.INVUSEID = M.INVUSEID
         AND L.INVUSELINEID = M.INVUSELINEID
   )
ORDER BY M.ACTUALDATE, M.MATUSETRANSID;
```


### B. Tranzacțiile care referă explicit consumurile acelei operațiuni

```sql
WITH LINIA AS (
    SELECT INVUSEID, INVUSELINEID
    FROM MATUSETRANS
    WHERE MATUSETRANSID = 222539
),
CONSUMURI AS (
    SELECT M.MATUSETRANSID
    FROM MATUSETRANS M
    WHERE M.MATUSETRANSID = 222539
       OR EXISTS (
           SELECT 1
           FROM LINIA L
           WHERE L.INVUSEID = M.INVUSEID
             AND L.INVUSELINEID = M.INVUSELINEID
       )
)
SELECT R.*
FROM MATUSETRANS R
WHERE R.ISSUEID IN (
    SELECT MATUSETRANSID
    FROM CONSUMURI
)
ORDER BY R.ACTUALDATE, R.MATUSETRANSID;
```


## 4. Dacă există un retur legat

Nu recomand eliminarea protecției.

De exemplu, dacă un consum este corectat de la `9,410` la `8,520`, dar returul său rămâne la `9,410`, am crea o nouă neconcordanță de valoare și de strat returnat.

În acest caz, avem două opțiuni:

- păstrăm refuzul pentru consumurile returnate în versiunea curentă;
- dezvoltăm un handler separat pentru consum și retururile sale legate, cu o regulă explicită de restaurare a straturilor.

Și auditul trebuie extins separat pentru retururi: în captura ta, mesajul `Tip RETURN fara alocare verificabila in jurnal` explică de ce mișcările ulterioare devin `U`. Nu este suficient să corectăm primul consum dacă motorul nu poate reconstrui apoi returul.[^55_1]

Trimite rezultatele celor două SELECT-uri. Ele ne spun exact de ce este refuzat `222539` și dacă următoarea extindere trebuie să trateze retururi sau o altă condiție de protecție.

<span style="display:none">[^55_2]</span>

<div align="center">⁂</div>

[^55_1]: image.jpg

[^55_2]: image.jpg


---

# stai... cred ca stiu de unde e problema (Sursa transmisa/legata/returnata; corectie automata refuzata). trebuie sa verific ce perioada financiara e deschisa. e posibil ca august sa nu fie inca deschisa...

Da, merită verificată perioada financiară înainte de continuarea corecțiilor. Totuși, perioada închisă nu este cauza **directă** a mesajului afișat acum.

## Ce declanșează mesajul actual

În scriptul livrat, textul:

```text
Sursa transmisa/legata/returnata; corectie automata refuzata
```

este generat dacă, pe unul dintre consumurile operațiunii, găsim:

```text
CXSENTEBS = True
sau FINCNTRLID completat
sau ISSUEID completat
sau QTYRETURNED diferit de zero
```

Această verificare nu citește starea deschisă/închisă a perioadei financiare. Prin urmare, deschiderea perioadei nu garantează că mesajul dispare. Acesta este mesajul observat în captura ta.[^56_1]

## Ce verificăm, separat

1. Perioada financiară aplicabilă tranzacției și dacă sunt permise corecțiile.
2. Câmpul exact care declanșează protecția noastră.

Pentru prima verificare a datelor tranzacției poți rula:

```sql
SELECT
    MATUSETRANSID,
    ACTUALDATE,
    TRANSDATE,
    FINANCIALPERIOD,
    CXSENTEBS,
    FINCNTRLID,
    ISSUEID,
    QTYRETURNED,
    INVUSEID,
    INVUSELINEID
FROM MATUSETRANS
WHERE MATUSETRANSID = 222539;
```

`FINANCIALPERIOD` nu trebuie interpretat automat ca numărul lunii. De exemplu, în exporturile anterioare, consumurile cu `ACTUALDATE` în iulie aveau `FINANCIALPERIOD='21'`.[^56_2]

Există și validarea locală `CXFINPERIODVALIDATION` asociată atributului `ACTUALDATE`, dar aceasta este distinctă de protecția din `CXFIFOFIXISSUE`.[^56_3]

Așadar, verifică perioada, dar nu eliminăm încă protecția și nu presupunem că aceasta este explicația completă. Dacă perioada permite corecția, trebuie tot să vedem care dintre cele patru condiții de mai sus este adevărată.

<div align="center">⁂</div>

[^56_1]: image.jpg

[^56_2]: MATUSETRANS_202610301519.csv

[^56_3]: SCRIPTLAUNCHPOINT_202610301521.csv


---

# nu cred ca e de la perioada financiara;

2\. am mai observat matusetransid-uri ulterioare 222539 cu date mai mari dupa 02.08
3\. apare ulterior si un retur cu matusetransid-uri mai mic decat 222539
4.asta e rezultatul selectului
(MATUSETRANSID,ACTUALDATE,TRANSDATE,FINANCIALPERIOD,CXSENTEBS,FINCNTRLID,ISSUEID,QTYRETURNED,INVUSEID,INVUSELINEID) VALUES
(222539,'2026-08-02 00:00:00.0','2026-10-29 13:26:44.553','22',0,NULL,NULL,5.000,69217,183728);

MATUSETRANS (MATUSETRANSID,ISSUETYPE,ACTUALDATE,QUANTITY,UNITCOST,ACTUALCOST,LINECOST,INVUSEID,INVUSELINEID,INVUSELINESPLITID,CXSENTEBS,FINCNTRLID,ISSUEID,QTYRETURNED) VALUES
(222539,'ISSUE','2026-08-02 00:00:00.0',-5.000,9.410,9.410,47.050,69217,183728,202297,0,NULL,NULL,5.000);

MATUSETRANS (ITEMNUM,STORELOC,TRANSDATE,ACTUALDATE,QUANTITY,CURBAL,PHYSCNT,UNITCOST,ACTUALCOST,PONUM,CONVERSION,ASSETNUM,ENTERBY,IT1,IT2,IT3,IT4,IT5,MEMO,OUTSIDE,ISSUETO,PACKINGSLIPNUM,POLINENUM,"ROLLUP",ITIN1,ITIN2,ITIN3,BINNUM,LOTNUM,ISSUETYPE,GLDEBITACCT,GLCREDITACCT,LINECOST,FINANCIALPERIOD,CURRENCYCODE,CURRENCYUNITCOST,ROTASSETNUM,CURRENCYLINECOST,LOCATION,DESCRIPTION,EXCHANGERATE,SPAREPARTADDED,QTYREQUESTED,EXCHANGERATE2,LINECOST2,MRNUM,MRLINENUM,MATUSETRANSID,MATRECTRANSID,IT6,IT7,IT8,IT9,IT10,ITIN4,ITIN5,ITIN6,ITIN7,SOURCESYSID,OWNERSYSID,EXTERNALREFID,SENDERSYSID,FINCNTRLID,ISSUEID,QTYRETURNED,ORGID,SITEID,REFWO,ENTEREDASTASK,LINETYPE,ITEMSETID,CONDITIONCODE,CONDRATE,COMMODITYGROUP,COMMODITY,TOSITEID,LANGCODE,HASLD,POREVISIONNUM,INVUSELINEID,INVUSEID,CONSIGNMENT,CONSINVOICENUM,CONSVENDOR,ISSUEUNIT,WPITEMID,INVPICKLISTID,INVUSELINESPLITID,ROWSTAMP,CXSENTEBS) VALUES
('230690001','C0220302MON','2026-10-29 13:28:42.796','2026-08-15 00:00:00.0',5.000,47.000,33.000,9.410,9.410,NULL,1.000,'E2042676','IRINA.SCARLAT',NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,NULL,'RETURN','C02-T211-19037-6022210000-12320-1200-0000-0000-000000','C02-T211-00000-3022200000-00000-0000-0000-0000-000000',-47.050,'22','RON',9.410,NULL,-47.050,NULL,'Ulei ptr actionari hidrostatice H 41',1.0000000,0,5.000,NULL,NULL,NULL,NULL,222566,1337430208,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,222539,NULL,'SNTFC','C02',NULL,0,'ITEM','SET1',NULL,100,'07',NULL,'C02','RO',0,0,183748,69223,0,NULL,NULL,'KG',-1,NULL,NULL,1868858792,0);

Acum cauza este demonstrată: scriptul refuză corecția deoarece consumul `222539` are **QTYRETURNED=5**, adică întreaga cantitate consumată a fost returnată.

Nu este necesar să presupunem o problemă de perioadă financiară pentru a explica acest mesaj.

## 1. Legătura exactă este 222539 → 222566

Din rezultatele transmise:


| Câmp | Consum | Retur |
| :-- | :-- | :-- |
| `MATUSETRANSID` | `222539` | `222566` |
| `ISSUETYPE` | `ISSUE` | `RETURN` |
| `ACTUALDATE` | 02.08.2026 | 15.08.2026 |
| `QUANTITY` | -5 | +5 |
| `UNITCOST` | 9,410 | 9,410 |
| `LINECOST` | +47,050 | -47,050 |
| `ISSUEID` | NULL | `222539` |

Returul `222566` indică explicit consumul prin:

```text
RETURN.ISSUEID = 222539
```

Iar suma cantităților returnate coincide cu `QTYRETURNED=5`.

Celelalte condiții ale protecției sunt inactive în rezultatul tău:

```text
CXSENTEBS = 0
FINCNTRLID = NULL
ISSUEID pe consum = NULL
```

Prin urmare, ramura care blochează este cea pentru cantitate returnată.

## 2. Returul cu ID mai mic din captură este altă tranzacție

`RETURN 222532`, afișat la 04.08.2026, nu trebuie asociat cu `222539` doar pentru că apare în apropiere. În captură există și returul `223493`; fiecare trebuie legat de consumul său folosind `ISSUEID`.[^57_1]

În cazul confirmat de tine, returul relevant este `222566`, care are:

- ID mai mare decât consumul;
- dată efectivă ulterioară;
- `TRANSDATE` ulterior;
- referință explicită la `222539`.

Așadar, pentru identificarea retururilor, `ISSUEID` este legătura decisivă, nu ordinea ID-urilor.

## 3. De ce nu trebuie să eliminăm pur și simplu protecția

Dacă modificăm numai consumul:

```text
ISSUE:  -5 × 8,520 → LINECOST +42,600
RETURN: +5 × 9,410 → LINECOST -47,050
```

perechea ar avea o diferență netă de valoare de `-4,450`, deși cantitatea netă este zero.

În starea actuală, perechea se compensează valoric:

```text
+47,050 − 47,050 = 0
```

Dar nici acest zero nu demonstrează că istoricul FIFO este corect: între 02.08 și 15.08 au existat alte mișcări. Nu putem șterge sau ignora perechea din reconstrucție ca și cum respectivele `5` unități n-ar fi ieșit niciodată.

## 4. Extinderea corectă a butonului

Propun o ramură distinctă pentru „consum cu retururi asociate”:

1. Selectezi tot rândul de ieșire.
2. Scriptul identifică operațiunea ISSUE și spliturile ei.
3. Citește toate retururile care referă aceste consumuri prin `ISSUEID`.
4. Verifică dacă retururile însumează cantitatea raportată în `QTYRETURNED`.
5. Construiește un plan comun pentru consum și retururile sale.
6. Corectează cantitățile/alocările numai unde este demonstrabil și sincronizează prețurile, valorile și jurnalul.
7. Recalculează soldurile ulterioare fără să ignore intervalul dintre consum și retur.

Pentru cazul simplu transmis, dacă alocarea de `5` unități la `8,520` se confirmă integral, ținta valorică ar fi:


| Tranzacție | Cantitate | PU corect | LINECOST corect |
| :-- | --: | --: | --: |
| `222539 ISSUE` | -5 | 8,520 | +42,600 |
| `222566 RETURN` | +5 | 8,520 | -42,600 |

Nu vom extinde automat aceeași regulă la retururi parțiale provenite din consumuri pe mai multe straturi: acolo trebuie demonstrat ce parte a fost returnată.

## 5. Ce rămâne neschimbat în delimitare

Putem păstra excluderile stabilite:

- fără actualizări explicite în `INVUSE`, `INVUSELINE` și `INVUSELINESPLIT`;
- fără modificarea recepțiilor `SHIPRECEIPT`;
- fără refacerea `INVLIFOFIFOCOST` în această etapă.

Dar ar trebui să permitem actualizarea unui `RETURN` strict atunci când este legat de ieșirea selectată. Altfel, handlerul trebuie să continue să refuze consumurile returnate.

Confirmi extinderea butonului 2 pentru a corecta și retururile `MATUSETRANS` legate explicit de consumul selectat prin `ISSUEID`, fără să atingă recepțiile obișnuite?

<span style="display:none">[^57_2]</span>

<div align="center">⁂</div>

[^57_1]: image.jpg

[^57_2]: image.jpg


---

# este finalizat scriptul?

**Nu încă pentru varianta extinsă cu retururi.** Ultimul script complet livrat este `CXFIFOFIXISSUE 2.4`, care corectează ieșirile ISSUE, dar refuză consumurile cu cantitate returnată — acesta este blocajul întâlnit la `222539`.[^59_1]

## Ce este livrat și ce mai lipsește

| Componentă | Stare |
| :-- | :-- |
| Corecția ISSUE și redistribuirea cantităților între rândurile existente | Livrată în 2.4 |
| Recuperarea situațiilor corectate parțial | Livrată în 2.4 |
| Excluderea actualizărilor explicite din `INVUSE`, `INVUSELINE`, `INVUSELINESPLIT` | Inclusă |
| Corecția comună a consumului și retururilor legate prin `ISSUEID` | Nu este încă implementată |
| Verificarea completă după salvare și reauditearea automată, fără refresh manual | Propusă, dar nu este încă finalizată |
| Validarea integrală în Maximo, inclusiv absența salvărilor parțiale/erorilor ROWSTAMP | Nu este încheiată |

Nu am generat încă un script nou care să corecteze perechea:

```text
222539 ISSUE  -5 → 222566 RETURN +5
```

Înainte să includ această ramură, trebuie confirmată extinderea domeniului: permiți actualizarea retururilor `MATUSETRANS` legate explicit de ieșirea selectată prin `ISSUEID`, păstrând recepțiile obișnuite și obiectele excluse nemodificate?

<div align="center">⁂</div>

[^59_1]: image.jpg


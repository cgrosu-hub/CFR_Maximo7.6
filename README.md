# Scripturi FIFO — revizia 13.11.2026

Pachetul contine sursele COMPLETE, fiecare independenta. Nucleul comun este inclus
in fiecare sursa; nu trebuie instalata o biblioteca separata.
Scripturile sunt pregatite ca fisiere, nu sunt instalate in Maximo.

## Fisiere

| Fisier | Versiune | Modificari principale |
| --- | --- | --- |
| CXFIFOFIXISSUE.py | 3.40-RECEIPT-SAFE | Validare comuna pentru consumul selectat si cascada; retururi cumulative; split distinct pe receptii chiar la acelasi pret; marcaj de reluare PAS1; verificarea valorilor dupa save; rollback PAS3 si rezultat de commit incert explicit. |
| CXINVAUDIT.py | 5.25-RECEIPT-SAFE | Verificare sold si provenienta pe receptie; retururi/anulari pe alocarile originale; refuz reconciliere pentru split/istoric/provenienta incomplete; INVBALANCES + INVLIFOFIFOCOST salvate atomic; Info FIFO simplificat. |
| CXUPDFIFOROW.py | 3.8-ATOMIC-SAME-DAY | Sursa, jurnalul si receptiile legate salvate intr-o singura tranzactie; zi locala pastrata; minute libere; acoperire din stoc net; numere citite/scrise fara double. |
| CXSTOCURIUPDATECURBAL.py | 2026.11.13-RECEIPT-LEDGER | Copie compatibila a jobului de recalcul: solduri pe pret si receptie. Necesara daca acel job ruleaza. |

## Regulile implementate

- CXSTOCURI.CXCURBAL este soldul DUPA miscare pe grupa, pret si receptie.
  INITIAL este un strat de deschidere separat. Nu este total articol–gestiune.
- La acelasi pret, doua receptii raman doua proveniente; nu se atribuie intregul
  consum primei receptii. Pentru un consum cu INVUSELINE, se creeaza splituri.
  O cale care nu suporta split refuza o provenienta multipla.
- Retururile succesive scad din cantitatea returnabila a alocarilor originale.
  Nu se creeaza stoc sintetic pentru cantitatea care depaseste consumul.
- Fragmentele noi au minute distincte in aceeasi zi din fusul orar al utilizatorului.
  Daca nu exista loc pana la urmatoarea miscare sau pana la miezul noptii,
  operatia se opreste cu mesaj; nu muta automat alte consumuri.
- Cursurile/conversiile diferite de 1, articolele rotating/lot/condition si destinatiile
  REFWO/ROLLUP neacoperite de handler sunt refuzate si pentru randurile din cascada.
- EBS: comportamentul existent este pastrat, conform confirmarii ca integrarea nu este activa.
- Query-urile repetitive din acelasi apel sunt memorate; provenientele sunt citite in loturi.

## Info FIFO cerut

Nu mai apar `FIFO LOCAL`, sectiunea numerica `; diferenta ...` sau
sectiunea `ATENTIE SOLD: negativ ...`. Marcajul BADFIFO si verificarea soldului
negativ raman active. Celelalte avertizari, de exemplu un sold lipsa, raman.

Exemplu:

`DIFERENTA: pret 1,000; asteptat 1,170 | Sursa=100 | BADFIFO=Y`

Formatul este recunoscut la urmatorul audit. Marcajul FIFO_SPLITS dintr-un PAS1
neterminat este pastrat pentru reluare; notele manuale nu sunt suprascrise automat.

## Salvare si reconciliere

Aceste versiuni salveaza in script. Dupa mesajul SALVAT nu se apasa suplimentar
Salvati inventarul. La PAS1 se reia butonul 2; PAS2 incearca si PAS3 automat;
daca PAS3 esueaza, se reciteste si se completeaza numai jurnalul lipsa.
La COMMIT INCERT nu se presupune nici succesul, nici absenta scrierii.

Reconcilierea oficiala se face numai cand auditul este complet. Nu se modifica
automat solduri oficiale negative si nu se alege arbitrar un cos dintre mai multe.
Nu se creeaza randuri INVLIFOFIFOCOST: daca nu sunt suficiente randuri reutilizabile,
intreaga reconciliere este sarita, inclusiv modificarea INVBALANCES. Reutilizarea
unui strat verifica si COSTDATE; daca data cheie nu poate fi pastrata, se face rollback.

In captura trimisa, CURBAL=-132,400 va fi raportat ca situatie care necesita
reconciliere explicita; nu este transformat automat intr-un sold pozitiv.

## Compatibilitate cu instalarea existenta

Numele scripturilor, optiunile, TABLE_ID si cheile mesajelor sunt pastrate.
Protectia existenta CXADDTOCXSTOCURI ramane necesara.
Daca CXSTOCURIUPDATECURBAL este activ, sursa compatibila inclusa trebuie folosita
impreuna cu cele trei scripturi; vechea versiune poate recalcula solduri cumulate
doar pe pret si ar anula separarea pe receptie.

Pe istoric vechi cu solduri cumulate pe pret, auditul va putea marca diferente.
Receptiile lipsa/ambigue nu sunt ghicite. Nu se face o migrare automata generala.
Lucrul concurent cu miscari noi ramane supus ROWSTAMP si verificarilor de snapshot;
aceasta revizie nu introduce un mecanism distribuit de blocare a intregii gestiuni.

## Verificari efectuate si limita lor

30 de verificari offline au trecut: exactitate numerica, receptii la acelasi pret,
retururi multiple si depasiri, identificarea provenientei gresite, totaluri fara
dublarea INITIAL, sloturi de timp, refuz la miezul noptii/intercalarea miscarilor,
pastrarea marcajului PAS1, format Info FIFO repetabil, oprire la split incomplet,
planificare fara reconciliere partiala si rollback cand un save simulat suprascrie planul.
S-a verificat sintaxa si absenta constructiilor specifice Python 3.

Testele ruleaza in CPython, cu inlocuitori pentru API-urile Java si MBO.
Nu sunt teste de integrare Jython/Maximo/DB2. Nu certifica evenimentele de save,
relatiile, restrictiile COSTDATE sau efectele automatizarilor instalate.
Sursele trebuie validate in mediul Maximo de test inainte de instalarea in productie.

Testele sunt in `tests/verify_fifo.py`; raportul sumar este `verificari.json`.
Copiile originale sunt in `originale/`; `manifest.json` contine SHA-256 pentru
sursele originale si cele revizuite. Fisierele originale din Desktop nu au fost schimbate.

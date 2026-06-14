# EA-LIE Mandatory Clause Playbook

> **Governing authority:** This playbook is the single source of truth for
> Thai-law mandatory provisions.  Every NDA and contract output by EA-LIE must
> embed all five clauses.  The `review_engine` deducts points for each gap.

---

## MC-01 — Injunctive Relief (CCC Art. 213)

**Tag:** `##MC:IR##`  
**Risk weight:** 20 points if missing

### Legal basis
Section 213 of the Civil and Commercial Code B.E. 2535 (Civil and Commercial
Code — CCC) grants a creditor the right to apply to the court for specific
performance or to compel the debtor to undo any act done in contravention.
Thai courts will grant interim injunctions where: (a) there is a serious
question to be tried; (b) the balance of convenience favours the applicant;
and (c) monetary damages would be inadequate.

### Required clause text (EN / TH)
See `lie/clauses.py :: INJUNCTIVE_RELIEF`.

### Checklist
- [ ] Explicit reference to CCC Section 213
- [ ] "irreparable harm" language
- [ ] No bond/security requirement waiver stated
- [ ] Not limited to monetary remedies

---

## MC-02 — Liquidated Damages ≥ THB 10,000,000 per Breach

**Tag:** `##MC:LD##`  
**Risk weight:** 20 points if missing; +10 if present but amount < THB 10M

### Legal basis
CCC Sections 379–381 allow parties to pre-agree penalty/LD amounts, though
courts may reduce a penalty that is excessively disproportionate to actual
damage (Section 383).  Minimum THB 10M per breach is the EA policy floor —
below this the deterrent effect is insufficient for EPC-scale contracts.

### Required clause text (EN / TH)
See `lie/clauses.py :: LD_THB10M`.

### Checklist
- [ ] Amount stated in THB (not USD or other currency)
- [ ] Amount ≥ THB 10,000,000 per breach
- [ ] "genuine pre-estimate" language (CCC Section 383 mitigation)
- [ ] Non-exclusive remedy statement

---

## MC-03 — PDPA / DPA Cross-Reference

**Tag:** `##MC:PDPA##`  
**Risk weight:** 20 points if missing

### Legal basis
Personal Data Protection Act B.E. 2562 (PDPA), effective 1 June 2022.
Any contract under which personal data is processed requires a Data Processing
Agreement (DPA) between controller and processor (PDPA Sections 40–41).
Failure to cross-reference the DPA creates direct regulatory exposure up to
THB 5M per violation.

### Required clause text (EN / TH)
See `lie/clauses.py :: PDPA_DPA_XREF`.

### Checklist
- [ ] References PDPA B.E. 2562 by name
- [ ] References the DPA executed between parties
- [ ] DPA-supremacy clause for data processing conflicts
- [ ] Covers both Thai and cross-border transfers

---

## MC-04 — SEC Act Disclosure Carve-Out

**Tag:** `##MC:SEC##`  
**Risk weight:** 20 points if missing

### Legal basis
Securities and Exchange Act B.E. 2535 and SEC notifications impose mandatory
disclosure obligations on listed companies and their affiliates.  A blanket
confidentiality clause without a carve-out for regulatory disclosure can
create criminal liability under the SEC Act (fine up to THB 500,000 and/or
imprisonment up to 2 years).

### Required clause text (EN / TH)
See `lie/clauses.py :: SEC_DISCLOSURE_CARVEOUT`.

### Checklist
- [ ] Carve-out for SEC Act B.E. 2535 disclosures
- [ ] Covers ก.ล.ต. (SEC Thailand) orders
- [ ] Prior notice obligation to counter-party
- [ ] Minimum-necessary-disclosure standard
- [ ] Cooperation in seeking protective orders

---

## MC-05 — Thai E-Signature Block

**Tag:** `##MC:ESIG##`  
**Risk weight:** 20 points if missing

### Legal basis
Electronic Transactions Act B.E. 2544 (ETA) and its amendments recognise
electronic signatures as legally equivalent to handwritten signatures provided
the method is reliable and appropriate to the purpose (ETA Section 9).
The Ministry of Digital Economy and Society Ministerial Regulation
(No. 3) B.E. 2564 governs qualified electronic signatures.

### Required clause text (EN / TH)
See `lie/clauses.py :: ESIGNATURE_THAI`.

### Checklist
- [ ] References ETA B.E. 2544 by name
- [ ] States equal legal effect to handwritten signature
- [ ] Authority confirmation from signatory
- [ ] Covers counterpart / split-execution scenario

---

## Score → Reviewer Assignment

| Score | RAG    | Reviewer           |
|-------|--------|--------------------|
| 0–34  | Green  | CTO + CFO          |
| 35–60 | Amber  | Legal Counsel      |
| 61–100| Red    | External Lawyer    |

**Scoring weights:**

| Finding                          | Points |
|----------------------------------|--------|
| Missing mandatory clause (each)  | 20     |
| LD amount < THB 10M              | 10     |
| Each problematic clause          | 3 (max 15) |
| Each risk factor extracted       | 5 (max 20) |

---

## FIDIC Timebar Reference

| Edition         | Clause  | Description                      | Days |
|-----------------|---------|----------------------------------|------|
| Red/Yellow 1999 | 20.1    | Notice of Claim                  | 28   |
| Red/Yellow 1999 | 2.5     | Employer's Claims                | 28   |
| Red/Yellow 1999 | 8.4     | Extension of Time notice         | 28   |
| Red/Yellow 1999 | 13.3    | Variation response               | 14   |
| Silver 1999     | 20.1    | Notice of Claim                  | 28   |
| Red 2017        | 20.2.1  | Notice of Claim (initial)        | 28   |
| Red 2017        | 20.2.4  | Fully detailed claim             | 84   |
| Yellow 2017     | 20.2.1  | Notice of Claim (initial)        | 28   |
| Gold 2008       | 20.1    | Notice of Claim                  | 28   |

**Alert thresholds:** 14 days, 7 days, 1 day before deadline.

---

*Last updated: 2026-06-14 — EA-LIE v0.1*

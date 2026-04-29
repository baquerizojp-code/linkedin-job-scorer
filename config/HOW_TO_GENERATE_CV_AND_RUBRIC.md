# How to generate your CV summary and scoring rubric with an LLM

The job scorer needs two configuration files tuned to **you**:

1. `config/cv_summary.md` — a condensed, scoring-optimized version of your CV
2. `config/rubric.md` — a 100-point weighted rubric describing what makes a job a good fit for you

Writing these by hand is tedious. The fastest path is to paste the prompt below into any capable LLM (ChatGPT, Claude, Gemini, etc.) along with your full CV and a description of the roles you're targeting. The LLM will return both files in the right shape.

---

## Step 1 — gather your inputs

You'll need:

- **Your full CV** — paste it as plain text or upload the file
- **A short description of your target search** — what kinds of roles you want, what you're avoiding, what your geographic constraints are, what your compensation floor and target are

---

## Step 2 — copy this prompt and paste it to an LLM

```
You are helping me configure a job-scoring automation. The automation reads job descriptions
and scores each one 0-100 against my profile, using two markdown files I need you to generate:

1. cv_summary.md — a condensed, scoring-optimized CV (about 1 page of markdown)
2. rubric.md — a 100-point weighted rubric (5 dimensions: Skills 50, Role Fit 20, Geo 5, Domain 15, Company Signal 10)

I'll give you my full CV and a description of my job search below. Read both, then return the
two files in this exact format, with no other text:

===== cv_summary.md =====
<the file content>
===== rubric.md =====
<the file content>

CV_SUMMARY REQUIREMENTS:
- Start with a one-line headline ("X yrs [discipline] · Y yrs [specialty] · [language(s)]")
- Sections: Skills (grouped by domain, with proficiency tags Expert/Strong/Working/Exposure/Gap),
  Target Roles (Full fit + Partial fit), Geo & Work Setup (location, time zone, work auth, languages),
  Domain Experience (Deep/Working/Exposure), Company Stage Fit (target stage, comp target + hard floor,
  dealbreakers).
- Be specific. Use real tool names, frameworks, and verticals from my CV.

RUBRIC REQUIREMENTS:
- Five dimensions with these exact weights and names: Skills Overlap (50), Role Fit (20), Geo / Remote (5),
  Domain Fit (15), Company Signal (10). Total must equal 100.
- Skills Overlap: list 3-5 "Core (5 pts each)" skills, 5-10 "Strong (3 pts each)" skills,
  and several "Nice-to-have (1 pt each)" skills. Cap at 50.
- Role Fit: list role titles that score full 20, then a few "pinned partial values" for adjacent roles,
  then a "Poor fit" tier that scores low but is still recorded.
- Geo: 5 if remote and not blocked for my country; 0 + red flag for hybrid/on-site outside my region or
  remote with country restrictions excluding mine.
- Domain Fit: 15 for my most-aligned domain, 12 for adjacent, 8 for general overlap, 4 for AI-adjacent
  but not core, 0 for unrelated. Add any bonus conditions specific to my search.
- Company Signal: tie to my comp target and hard floor. Missing comp is NOT a red flag — only explicit
  comp below my hard floor is.
- End with a "Recommendation Mapping" (Apply >=70, Review 50-69, Skip <50) and an "Auto Red Flags" list
  tailored to my dealbreakers.

Be calibrated, not generous. Use my actual experience level honestly. If I claim a skill at "Expert"
in my CV, mark it Expert; if it's only mentioned in passing, mark it Working or Exposure.

Here is my full CV:

<<< PASTE YOUR FULL CV HERE >>>

Here is my job search description (target roles, comp, geo, dealbreakers, anything important):

<<< DESCRIBE YOUR SEARCH HERE >>>

Return both files now, separated by the markers above and nothing else.
```

---

## Step 3 — save the output

The LLM will return two blocks separated by `===== cv_summary.md =====` and `===== rubric.md =====`.

1. Copy the content under `===== cv_summary.md =====` into `config/cv_summary.md`
2. Copy the content under `===== rubric.md =====` into `config/rubric.md`

(Both files are gitignored — your personal CV stays on your machine.)

---

## Step 4 — review and tune

Read both files. Edit anything that's wrong. Pay particular attention to:

- **Skills tier accuracy** — are you really an "Expert" in everything the LLM tagged as Expert?
- **Role Fit list completeness** — did it miss any adjacent role titles you'd consider?
- **Comp floor and dealbreakers** — these drive red-flag detection at scoring time

You can re-run the LLM with edits ("regenerate cv_summary but mark Python as 'Working' not 'Strong'") as many times as you need.

---

## Step 5 — iterate over time

As you run the scorer and see how it scores real jobs, you may notice it's too generous in one dimension or missing a skill that keeps showing up. Edit the files directly. The script reads them fresh on every run, so changes take effect immediately on the next run.

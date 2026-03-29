"""
AssamBoard Subject Router
=========================
Four-tier subject classifier for AHSEC / SEBA / DEGREE queries.

Tier 0  — Syllabus DB vector search  (~98 % accuracy, ~80 ms, live syllabus)
Tier 1  — Keyword match              (~95 % hit rate, <5 ms, offline)
Tier 2  — Scored partial match       (~4 %,           <20 ms)
Tier 3  — LLM micro-classify         (~1 %,           ~100 ms)

Returns a SubjectRoute with board, class, stream, subject, chapter hint
and confidence so callers can enrich web-search queries and RAG scoping.
"""

from __future__ import annotations
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional, Callable, Awaitable

logger = logging.getLogger("subject_router")

# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SubjectRoute:
    board: str               # AHSEC | SEBA | DEGREE
    class_name: str          # HS 1st Year | HS 2nd Year | 2nd Sem | 4th Sem | Class 9 | Class 10
    stream: str              # Science (PCM) | Commerce | Arts | B.Com | B.A | B.Sc | General
    subject: str             # Business Studies | Physics | …
    chapter_hint: str = ""   # Most likely chapter name (may be empty)
    confidence: str = "high" # high | medium | low
    scope_query: str = ""    # ready-made search-scoped string (board + class + subject + query)

    def build_scope(self, user_query: str) -> "SubjectRoute":
        parts = [self.board, self.class_name, self.stream, self.subject, user_query]
        self.scope_query = " ".join(p for p in parts if p)
        return self


# ──────────────────────────────────────────────────────────────────────────────
# Keyword registry
# Each entry: (frozenset_of_keywords, SubjectRoute_template)
# Keywords are checked as: ALL words in the frozenset appear in query (case-insensitive).
# ──────────────────────────────────────────────────────────────────────────────

def _r(board, cls, stream, subject, chapter=""):
    return SubjectRoute(board=board, class_name=cls, stream=stream,
                        subject=subject, chapter_hint=chapter)

_AHSEC12 = "HS 2nd Year"
_AHSEC11 = "HS 1st Year"
_DEG2    = "2nd Semester"
_DEG4    = "4th Semester"
_SB9     = "Class 9"
_SB10    = "Class 10"

KEYWORD_ROUTES: list[tuple[frozenset, SubjectRoute]] = [

    # ══════════════════════════════════════════════════════════════════════════
    # BUSINESS STUDIES  (AHSEC Class 11 & 12 Commerce)
    # ══════════════════════════════════════════════════════════════════════════
    # Management chapters
    (frozenset(["nature","significance","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Nature and Significance of Management")),
    (frozenset(["functions","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Nature and Significance of Management")),
    (frozenset(["management","definition"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Nature and Significance of Management")),
    (frozenset(["fayol","principles"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Principles of Management")),
    (frozenset(["taylor","scientific","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Principles of Management")),
    (frozenset(["unity","command"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Principles of Management")),
    (frozenset(["division","work","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Principles of Management")),
    (frozenset(["esprit","de","corps"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Principles of Management")),
    # Business Environment
    (frozenset(["government","role","business"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Business Environment")),
    (frozenset(["govt","role","business"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Business Environment")),
    (frozenset(["liberalisation","privatisation","globalisation"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Business Environment")),
    (frozenset(["lpg","reforms","business"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Business Environment")),
    (frozenset(["business","environment","economic"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Business Environment")),
    (frozenset(["mrp","act","licensing"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Business Environment")),
    (frozenset(["privatization","disinvestment"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Business Environment")),
    # Planning
    (frozenset(["planning","features","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Planning")),
    (frozenset(["planning","process","steps"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Planning")),
    (frozenset(["planning","limitations","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Planning")),
    # Organising
    (frozenset(["delegation","authority"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Organising")),
    (frozenset(["decentralisation","centralisation"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Organising")),
    (frozenset(["formal","informal","organisation"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Organising")),
    (frozenset(["organising","management","structure"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Organising")),
    (frozenset(["span","control","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Organising")),
    # Staffing
    (frozenset(["staffing","process","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Staffing")),
    (frozenset(["recruitment","selection","training"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Staffing")),
    (frozenset(["induction","training","employees"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Staffing")),
    (frozenset(["performance","appraisal","hrm"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Staffing")),
    # Directing
    (frozenset(["directing","management","leadership"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Directing")),
    (frozenset(["maslow","hierarchy","needs"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Directing")),
    (frozenset(["herzberg","motivation","hygiene"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Directing")),
    (frozenset(["leadership","styles","autocratic"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Directing")),
    (frozenset(["communication","channels","formal"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Directing")),
    # Controlling
    (frozenset(["controlling","process","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Controlling")),
    (frozenset(["benchmarking","management","control"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Controlling")),
    (frozenset(["deviation","corrective","action","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Controlling")),
    # Financial Management
    (frozenset(["financial","management","capital","structure"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Financial Management")),
    (frozenset(["working","capital","management"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Financial Management")),
    (frozenset(["capital","budgeting","investment"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Financial Management")),
    (frozenset(["dividend","decision","finance"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Financial Management")),
    (frozenset(["leverage","financial","operating"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Financial Management")),
    # Financial Markets
    (frozenset(["stock","exchange","sebi"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Financial Markets")),
    (frozenset(["primary","secondary","market","shares"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Financial Markets")),
    (frozenset(["debentures","bonds","money","market"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Financial Markets")),
    (frozenset(["nse","bse","sensex","nifty"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Financial Markets")),
    # Marketing Management
    (frozenset(["marketing","mix","4p"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Marketing Management")),
    (frozenset(["product","price","place","promotion"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Marketing Management")),
    (frozenset(["consumer","behaviour","marketing"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Marketing Management")),
    (frozenset(["branding","packaging","labelling"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Marketing Management")),
    (frozenset(["advertising","sales","promotion"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Marketing Management")),
    # Consumer Protection
    (frozenset(["consumer","protection","rights"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Consumer Protection")),
    (frozenset(["consumer","forum","grievance"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Consumer Protection")),
    (frozenset(["copra","consumer","act"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Consumer Protection")),
    # Entrepreneurship
    (frozenset(["entrepreneurship","entrepreneur","innovation"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Business Studies", "Entrepreneurship Development")),

    # Business Studies Class 11
    (frozenset(["forms","business","organisation"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Business Studies", "Forms of Business Organisation")),
    (frozenset(["sole","proprietorship","partnership"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Business Studies", "Forms of Business Organisation")),
    (frozenset(["joint","stock","company","class","11"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Business Studies", "Forms of Business Organisation")),
    (frozenset(["cooperative","society","business"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Business Studies", "Forms of Business Organisation")),
    (frozenset(["business","trade","commerce","class","11"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Business Studies", "Business Trade and Commerce")),
    (frozenset(["internal","trade","wholesale","retail"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Business Studies", "Internal Trade")),
    (frozenset(["social","responsibility","business","ethics"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Business Studies", "Social Responsibilities of Business")),

    # ══════════════════════════════════════════════════════════════════════════
    # ACCOUNTANCY  (AHSEC Class 11 & 12 Commerce)
    # ══════════════════════════════════════════════════════════════════════════
    # Class 12
    (frozenset(["partnership","accounting","admission"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Admission of a Partner")),
    (frozenset(["admission","partner","goodwill"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Admission of a Partner")),
    (frozenset(["retirement","death","partner"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Retirement and Death of a Partner")),
    (frozenset(["dissolution","partnership","firm"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Dissolution of Partnership Firm")),
    (frozenset(["share","capital","accounting"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Accounting for Share Capital")),
    (frozenset(["issue","shares","premium","discount"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Accounting for Share Capital")),
    (frozenset(["debentures","issue","redemption"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Issue and Redemption of Debentures")),
    (frozenset(["cash","flow","statement"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Cash Flow Statement")),
    (frozenset(["ratio","analysis","financial"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Analysis of Financial Statements")),
    (frozenset(["profit","sharing","ratio","partnership"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Accounting for Partnership — Basic Concepts")),
    (frozenset(["sacrificing","ratio","gaining","ratio"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Accountancy", "Change in Profit Sharing Ratio")),
    # Class 11
    (frozenset(["journal","ledger","trial","balance"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Accountancy", "Recording of Transactions")),
    (frozenset(["bank","reconciliation","statement"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Accountancy", "Bank Reconciliation Statement")),
    (frozenset(["depreciation","provisions","reserves"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Accountancy", "Depreciation Provisions and Reserves")),
    (frozenset(["bill","exchange","accounting"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Accountancy", "Bill of Exchange")),
    (frozenset(["final","accounts","trading","profit","loss"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Accountancy", "Financial Statements")),
    (frozenset(["debit","credit","double","entry"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Accountancy", "Theory Base of Accounting")),
    (frozenset(["accounting","concepts","conventions"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Accountancy", "Theory Base of Accounting")),

    # ══════════════════════════════════════════════════════════════════════════
    # ECONOMICS  (AHSEC Class 11 & 12  — Arts & Commerce)
    # ══════════════════════════════════════════════════════════════════════════
    # Macroeconomics (Class 12)
    (frozenset(["national","income","gdp","gnp"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "National Income Accounting")),
    (frozenset(["gdp","real","nominal","deflator"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "National Income Accounting")),
    (frozenset(["money","banking","central","bank"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Money and Banking")),
    (frozenset(["rbi","monetary","policy","repo"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Money and Banking")),
    (frozenset(["multiplier","aggregate","demand"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Determination of Income and Employment")),
    (frozenset(["fiscal","policy","government","budget"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Government Budget and the Economy")),
    (frozenset(["balance","payments","trade","current","account"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Open Economy Macroeconomics")),
    (frozenset(["foreign","exchange","rate","depreciation","currency"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Open Economy Macroeconomics")),
    (frozenset(["indian","economy","independence","1991"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Liberalisation Privatisation and Globalisation")),
    (frozenset(["poverty","unemployment","india","economy"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Poverty")),
    (frozenset(["human","capital","education","health","economy"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Human Capital Formation")),
    (frozenset(["rural","development","agriculture","india"]),
     _r("AHSEC", _AHSEC12, "Commerce", "Economics", "Rural Development")),
    # Microeconomics (Class 11)
    (frozenset(["demand","supply","elasticity","economics"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Economics", "Introduction to Microeconomics")),
    (frozenset(["law","demand","price","quantity"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Economics", "Introduction to Microeconomics")),
    (frozenset(["consumer","equilibrium","indifference","curve"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Economics", "Consumer Behaviour")),
    (frozenset(["budget","line","consumer","preference"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Economics", "Consumer Behaviour")),
    (frozenset(["market","forms","perfect","monopoly","oligopoly"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Economics", "Market Forms")),
    (frozenset(["statistics","economics","index","number"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Economics", "Introduction to Statistics for Economics")),
    (frozenset(["mean","median","mode","measures","central","tendency"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Economics", "Measures of Central Tendency")),
    (frozenset(["correlation","karl","pearson","spearman"]),
     _r("AHSEC", _AHSEC11, "Commerce", "Economics", "Correlation")),

    # ══════════════════════════════════════════════════════════════════════════
    # PHYSICS  (AHSEC Class 11 & 12 — PCM & PCB; DEGREE B.Sc)
    # ══════════════════════════════════════════════════════════════════════════
    # Class 12 chapters
    (frozenset(["electric","charges","fields","coulomb"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Electric Charges and Fields")),
    (frozenset(["gauss","law","electric","flux"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Electric Charges and Fields")),
    (frozenset(["electrostatic","potential","capacitance"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Electrostatic Potential and Capacitance")),
    (frozenset(["capacitor","dielectric","parallel","plate"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Electrostatic Potential and Capacitance")),
    (frozenset(["ohm","kirchhoff","current","electricity"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Current Electricity")),
    (frozenset(["resistivity","conductivity","drift","velocity"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Current Electricity")),
    (frozenset(["wheatstone","bridge","meter","bridge"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Current Electricity")),
    (frozenset(["moving","charges","magnetism","lorentz"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Moving Charges and Magnetism")),
    (frozenset(["ampere","biot","savart","solenoid"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Moving Charges and Magnetism")),
    (frozenset(["electromagnetic","induction","faraday","lenz"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Electromagnetic Induction")),
    (frozenset(["alternating","current","ac","transformer"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Alternating Current")),
    (frozenset(["impedance","resonance","lc","rlc","circuit"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Alternating Current")),
    (frozenset(["ray","optics","refraction","lens","mirror"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Ray Optics")),
    (frozenset(["total","internal","reflection","prism"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Ray Optics")),
    (frozenset(["wave","optics","interference","diffraction"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Wave Optics")),
    (frozenset(["young","double","slit","experiment"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Wave Optics")),
    (frozenset(["photoelectric","effect","photon","work","function"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Dual Nature of Radiation")),
    (frozenset(["de","broglie","wave","matter"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Dual Nature of Radiation")),
    (frozenset(["bohr","model","atom","hydrogen","spectrum"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Atoms")),
    (frozenset(["nuclear","fission","fusion","binding","energy"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Nuclei")),
    (frozenset(["radioactivity","alpha","beta","gamma","decay"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Nuclei")),
    (frozenset(["semiconductor","diode","transistor","logic","gate"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Semiconductor Electronics")),
    (frozenset(["p-n","junction","rectifier","zener"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Physics", "Semiconductor Electronics")),
    # Class 11 Physics chapters
    (frozenset(["kinematics","projectile","velocity","acceleration"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Physics", "Kinematics")),
    (frozenset(["newton","laws","motion","friction"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Physics", "Laws of Motion")),
    (frozenset(["work","energy","power","kinetic","potential"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Physics", "Work Energy and Power")),
    (frozenset(["gravitation","kepler","satellite","orbital"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Physics", "Gravitation")),
    (frozenset(["thermodynamics","heat","entropy","carnot"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Physics", "Thermodynamics")),
    (frozenset(["kinetic","theory","gas","maxwell"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Physics", "Behaviour of Perfect Gas and Kinetic Theory")),
    (frozenset(["simple","harmonic","motion","oscillation"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Physics", "Oscillations")),

    # ══════════════════════════════════════════════════════════════════════════
    # CHEMISTRY  (AHSEC Class 11 & 12 — PCM & PCB)
    # ══════════════════════════════════════════════════════════════════════════
    # Class 12
    (frozenset(["solid","state","crystal","amorphous","unit","cell"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "The Solid State")),
    (frozenset(["solutions","mole","fraction","osmosis","raoult"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Solutions")),
    (frozenset(["electrochemistry","galvanic","cell","emf","nernst"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Electrochemistry")),
    (frozenset(["electrolysis","faraday","laws","electrochemistry"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Electrochemistry")),
    (frozenset(["chemical","kinetics","rate","reaction","order"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Chemical Kinetics")),
    (frozenset(["activation","energy","arrhenius","equation"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Chemical Kinetics")),
    (frozenset(["surface","chemistry","adsorption","colloid","catalyst"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Surface Chemistry")),
    (frozenset(["p","block","elements","group","15","16","17","18"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "The p-Block Elements")),
    (frozenset(["nitrogen","family","oxygen","family","halogen"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "The p-Block Elements")),
    (frozenset(["noble","gas","xenon","fluorides"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "The p-Block Elements")),
    (frozenset(["d","block","transition","metals","properties"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "The d and f Block Elements")),
    (frozenset(["lanthanides","actinides","f","block"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "The d and f Block Elements")),
    (frozenset(["coordination","compounds","ligands","cfse","isomerism"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Coordination Compounds")),
    (frozenset(["werner","theory","coordination","complex"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Coordination Compounds")),
    (frozenset(["haloalkanes","haloarenes","alkyl","halide"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Haloalkanes and Haloarenes")),
    (frozenset(["alcohol","phenol","ether","organic"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Alcohols Phenols and Ethers")),
    (frozenset(["aldehyde","ketone","carboxylic","acid"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Aldehydes Ketones and Carboxylic Acids")),
    (frozenset(["amines","diazonium","amine","basicity"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Amines")),
    (frozenset(["biomolecules","carbohydrate","protein","nucleic","acid"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Biomolecules")),
    (frozenset(["polymer","addition","condensation","rubber"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Chemistry", "Polymers")),
    # Class 11 Chemistry
    (frozenset(["structure","atom","bohr","quantum","number"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "Structure of Atom")),
    (frozenset(["periodic","table","classification","elements"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "Classification of Elements and Periodicity")),
    (frozenset(["chemical","bonding","ionic","covalent","hybridisation"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "Chemical Bonding and Molecular Structure")),
    (frozenset(["vsepr","molecular","geometry","shape"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "Chemical Bonding and Molecular Structure")),
    (frozenset(["states","matter","gas","ideal","van","der","waals"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "States of Matter")),
    (frozenset(["thermodynamics","enthalpy","entropy","gibbs","free","energy"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "Thermodynamics")),
    (frozenset(["equilibrium","le","chatelier","kc","kp"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "Equilibrium")),
    (frozenset(["redox","reaction","oxidation","reduction","balancing"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "Redox Reactions")),
    (frozenset(["s","block","alkali","alkaline","earth","metal"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "s-Block Elements")),
    (frozenset(["organic","chemistry","homologous","iupac"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Chemistry", "Organic Chemistry — Basic Principles")),

    # ══════════════════════════════════════════════════════════════════════════
    # MATHEMATICS  (AHSEC Class 11 & 12 — PCM)
    # ══════════════════════════════════════════════════════════════════════════
    (frozenset(["matrices","determinants","operations"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Matrices")),
    (frozenset(["inverse","matrix","rank","system","equations"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Matrices")),
    (frozenset(["determinant","cofactor","cramer","rule"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Determinants")),
    (frozenset(["continuity","differentiability","limit","function"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Continuity and Differentiability")),
    (frozenset(["derivative","differentiation","chain","rule"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Continuity and Differentiability")),
    (frozenset(["application","derivatives","maxima","minima","tangent"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Application of Derivatives")),
    (frozenset(["integration","indefinite","definite","integral"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Integrals")),
    (frozenset(["differential","equation","order","degree","solution"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Differential Equations")),
    (frozenset(["vector","algebra","dot","cross","product"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Vector Algebra")),
    (frozenset(["three","dimensional","geometry","direction","cosines"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Three Dimensional Geometry")),
    (frozenset(["linear","programming","objective","feasible","region"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Linear Programming")),
    (frozenset(["probability","bayes","theorem","conditional"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Probability")),
    (frozenset(["relations","functions","domain","range","codomain"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Relations and Functions")),
    (frozenset(["inverse","trigonometric","functions","arcsin"]),
     _r("AHSEC", _AHSEC12, "Science (PCM)", "Mathematics", "Inverse Trigonometric Functions")),
    # Class 11 Maths
    (frozenset(["sets","union","intersection","complement","venn"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Mathematics", "Sets")),
    (frozenset(["trigonometric","functions","sine","cosine","identity"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Mathematics", "Trigonometric Functions")),
    (frozenset(["complex","numbers","argand","plane","modulus"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Mathematics", "Complex Numbers and Quadratic Equations")),
    (frozenset(["permutations","combinations","nCr","nPr","factorial"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Mathematics", "Permutations and Combinations")),
    (frozenset(["binomial","theorem","expansion","coefficient"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Mathematics", "Binomial Theorem")),
    (frozenset(["arithmetic","geometric","progression","sequence","series"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Mathematics", "Sequences and Series")),
    (frozenset(["straight","lines","slope","equation","line"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Mathematics", "Straight Lines")),
    (frozenset(["conic","sections","parabola","ellipse","hyperbola"]),
     _r("AHSEC", _AHSEC11, "Science (PCM)", "Mathematics", "Conic Sections")),

    # ══════════════════════════════════════════════════════════════════════════
    # BIOLOGY  (AHSEC Class 11 & 12 — PCB)
    # ══════════════════════════════════════════════════════════════════════════
    # Class 12
    (frozenset(["reproduction","organisms","sexual","asexual"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Reproduction in Organisms")),
    (frozenset(["flowering","plants","pollination","fertilisation"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Sexual Reproduction in Flowering Plants")),
    (frozenset(["human","reproduction","gametogenesis","menstrual"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Human Reproduction")),
    (frozenset(["mendelian","genetics","inheritance","law","segregation"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Principles of Inheritance and Variation")),
    (frozenset(["dna","rna","replication","transcription","translation"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Molecular Basis of Inheritance")),
    (frozenset(["evolution","natural","selection","darwin","origin","species"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Evolution")),
    (frozenset(["biotechnology","recombinant","dna","pcr","gel","electrophoresis"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Biotechnology — Principles and Processes")),
    (frozenset(["ecosystem","food","chain","web","energy","flow"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Ecosystem")),
    (frozenset(["population","ecology","carrying","capacity","niche"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Organisms and Populations")),
    (frozenset(["human","health","disease","immunity","vaccine"]),
     _r("AHSEC", _AHSEC12, "Science (PCB)", "Biology", "Human Health and Disease")),
    # Class 11
    (frozenset(["cell","unit","life","organelles","membrane"]),
     _r("AHSEC", _AHSEC11, "Science (PCB)", "Biology", "Cell — The Unit of Life")),
    (frozenset(["cell","division","mitosis","meiosis"]),
     _r("AHSEC", _AHSEC11, "Science (PCB)", "Biology", "Cell Division")),
    (frozenset(["biomolecules","carbohydrates","proteins","enzymes","lipids"]),
     _r("AHSEC", _AHSEC11, "Science (PCB)", "Biology", "Biomolecules")),
    (frozenset(["plant","kingdom","algae","bryophyta","pteridophyta"]),
     _r("AHSEC", _AHSEC11, "Science (PCB)", "Biology", "Plant Kingdom")),
    (frozenset(["animal","kingdom","porifera","coelenterata","chordata"]),
     _r("AHSEC", _AHSEC11, "Science (PCB)", "Biology", "Animal Kingdom")),
    (frozenset(["transport","plants","xylem","phloem","transpiration"]),
     _r("AHSEC", _AHSEC11, "Science (PCB)", "Biology", "Transport in Plants")),

    # ══════════════════════════════════════════════════════════════════════════
    # POLITICAL SCIENCE  (AHSEC Class 11 & 12 — Arts)
    # ══════════════════════════════════════════════════════════════════════════
    (frozenset(["cold","war","bipolar","nato","warsaw"]),
     _r("AHSEC", _AHSEC12, "Arts", "Political Science", "The Cold War Era")),
    (frozenset(["us","hegemony","unipolar","world","politics"]),
     _r("AHSEC", _AHSEC12, "Arts", "Political Science", "US Hegemony in World Politics")),
    (frozenset(["united","nations","security","council","reform"]),
     _r("AHSEC", _AHSEC12, "Arts", "Political Science", "International Organisations")),
    (frozenset(["globalisation","political","science"]),
     _r("AHSEC", _AHSEC12, "Arts", "Political Science", "Globalisation")),
    (frozenset(["indian","constitution","making","constituent","assembly"]),
     _r("AHSEC", _AHSEC12, "Arts", "Political Science", "Challenges of Nation Building")),
    (frozenset(["fundamental","rights","directive","principles","dpsp"]),
     _r("AHSEC", _AHSEC11, "Arts", "Political Science", "Freedom")),
    (frozenset(["secularism","india","state","religion"]),
     _r("AHSEC", _AHSEC11, "Arts", "Political Science", "Secularism")),
    (frozenset(["nationalism","citizenship","political","theory"]),
     _r("AHSEC", _AHSEC11, "Arts", "Political Science", "Nationalism")),

    # ══════════════════════════════════════════════════════════════════════════
    # HISTORY  (AHSEC Class 11 & 12 — Arts)
    # ══════════════════════════════════════════════════════════════════════════
    (frozenset(["harappan","civilisation","indus","valley","mohenjo"]),
     _r("AHSEC", _AHSEC12, "Arts", "History", "Bricks Beads and Bones — Harappan Civilisation")),
    (frozenset(["mughal","empire","akbar","shahjahan","aurangzeb"]),
     _r("AHSEC", _AHSEC12, "Arts", "History", "The Mughal Court")),
    (frozenset(["colonial","india","british","rule","company"]),
     _r("AHSEC", _AHSEC12, "Arts", "History", "Colonialism and the Countryside")),
    (frozenset(["mahatma","gandhi","nationalist","movement"]),
     _r("AHSEC", _AHSEC12, "Arts", "History", "Mahatma Gandhi and the Nationalist Movement")),
    (frozenset(["partition","india","1947","communal"]),
     _r("AHSEC", _AHSEC12, "Arts", "History", "Understanding Partition")),
    (frozenset(["1857","revolt","sepoy","mutiny"]),
     _r("AHSEC", _AHSEC12, "Arts", "History", "Rebels and the Raj")),
    (frozenset(["framing","constitution","india","ambedkar"]),
     _r("AHSEC", _AHSEC12, "Arts", "History", "Framing the Constitution")),
    # Class 11
    (frozenset(["mesopotamia","writing","city","life","ancient"]),
     _r("AHSEC", _AHSEC11, "Arts", "History", "Writing and City Life — Mesopotamia")),
    (frozenset(["industrial","revolution","britain","capitalism"]),
     _r("AHSEC", _AHSEC11, "Arts", "History", "The Industrial Revolution")),

    # ══════════════════════════════════════════════════════════════════════════
    # GEOGRAPHY  (AHSEC Class 11 & 12 — Arts)
    # ══════════════════════════════════════════════════════════════════════════
    (frozenset(["human","geography","nature","scope"]),
     _r("AHSEC", _AHSEC12, "Arts", "Geography", "Human Geography — Nature and Scope")),
    (frozenset(["world","population","distribution","density","growth"]),
     _r("AHSEC", _AHSEC12, "Arts", "Geography", "The World Population Distribution Density and Growth")),
    (frozenset(["international","trade","geography","economic"]),
     _r("AHSEC", _AHSEC12, "Arts", "Geography", "International Trade")),
    (frozenset(["transport","communication","geography","network"]),
     _r("AHSEC", _AHSEC12, "Arts", "Geography", "Transport and Communication")),
    (frozenset(["atmosphere","composition","layers","geography"]),
     _r("AHSEC", _AHSEC11, "Arts", "Geography", "Atmosphere — Composition and Structure")),
    (frozenset(["climate","change","global","warming","greenhouse"]),
     _r("AHSEC", _AHSEC11, "Arts", "Geography", "World Climate and Climate Change")),
    (frozenset(["landforms","evolution","weathering","erosion"]),
     _r("AHSEC", _AHSEC11, "Arts", "Geography", "Landforms and Their Evolution")),

    # ══════════════════════════════════════════════════════════════════════════
    # DEGREE — B.COM  (2nd Sem & 4th Sem)
    # ══════════════════════════════════════════════════════════════════════════
    # 2nd Sem B.Com
    (frozenset(["theory","demand","elasticity","degree"]),
     _r("DEGREE", _DEG2, "B.Com", "Business Economics", "Theory of Demand")),
    (frozenset(["market","structure","degree","bcom","economics"]),
     _r("DEGREE", _DEG2, "B.Com", "Business Economics", "Market Structures")),
    (frozenset(["journal","entries","degree","financial","accounting"]),
     _r("DEGREE", _DEG2, "B.Com", "Financial Accounting", "Journal Entries")),
    (frozenset(["consignment","joint","venture","accounts"]),
     _r("DEGREE", _DEG2, "B.Com", "Financial Accounting", "Consignment Accounts")),
    (frozenset(["business","communication","letter","report","writing"]),
     _r("DEGREE", _DEG2, "B.Com", "Business Communication", "Business Letters")),
    (frozenset(["business","mathematics","matrices","bcom"]),
     _r("DEGREE", _DEG2, "B.Com", "Business Mathematics", "Matrices")),
    (frozenset(["simple","compound","interest","annuity","degree"]),
     _r("DEGREE", _DEG2, "B.Com", "Business Mathematics", "Simple and Compound Interest")),
    # 4th Sem B.Com
    (frozenset(["cost","accounting","marginal","job","process"]),
     _r("DEGREE", _DEG4, "B.Com", "Cost Accounting", "Marginal Costing")),
    (frozenset(["standard","costing","variance","analysis"]),
     _r("DEGREE", _DEG4, "B.Com", "Cost Accounting", "Standard Costing")),
    (frozenset(["income","tax","salary","head","income","degree"]),
     _r("DEGREE", _DEG4, "B.Com", "Income Tax", "Income from Salary")),
    (frozenset(["income","tax","capital","gains","deductions"]),
     _r("DEGREE", _DEG4, "B.Com", "Income Tax", "Capital Gains")),
    (frozenset(["contract","act","1872","offer","acceptance","consideration"]),
     _r("DEGREE", _DEG4, "B.Com", "Business Law", "Indian Contract Act 1872")),
    (frozenset(["sale","goods","act","1930","buyer","seller"]),
     _r("DEGREE", _DEG4, "B.Com", "Business Law", "Sale of Goods Act 1930")),
    (frozenset(["companies","act","company","law","bcom"]),
     _r("DEGREE", _DEG4, "B.Com", "Business Law", "Companies Act")),
    (frozenset(["principles","management","degree","planning","organising"]),
     _r("DEGREE", _DEG4, "B.Com", "Principles of Management", "Planning")),

    # ══════════════════════════════════════════════════════════════════════════
    # DEGREE — B.A  (2nd Sem & 4th Sem)
    # ══════════════════════════════════════════════════════════════════════════
    (frozenset(["english","literature","poetry","prose","degree","ba"]),
     _r("DEGREE", _DEG2, "B.A", "English Literature", "Poetry — Romantic to Modern")),
    (frozenset(["political","theory","liberty","equality","degree"]),
     _r("DEGREE", _DEG2, "B.A", "Political Science", "Political Theory")),
    (frozenset(["indian","constitution","degree","ba","union"]),
     _r("DEGREE", _DEG2, "B.A", "Political Science", "Indian Constitution")),
    (frozenset(["modern","india","history","degree","ba","nehru"]),
     _r("DEGREE", _DEG4, "B.A", "Modern Indian History", "Nehru Era")),
    (frozenset(["economic","reforms","1991","degree","ba"]),
     _r("DEGREE", _DEG4, "B.A", "Indian Economy", "Economic Reforms 1991")),
    (frozenset(["five","year","plans","planning","commission","india"]),
     _r("DEGREE", _DEG4, "B.A", "Indian Economy", "Five-Year Plans")),
    (frozenset(["parliament","india","lok","sabha","rajya","degree"]),
     _r("DEGREE", _DEG4, "B.A", "Indian Government & Politics", "Parliament")),
    (frozenset(["judiciary","supreme","court","high","court","india"]),
     _r("DEGREE", _DEG4, "B.A", "Indian Government & Politics", "Judiciary")),

    # ══════════════════════════════════════════════════════════════════════════
    # DEGREE — B.SC  (2nd Sem & 4th Sem)
    # ══════════════════════════════════════════════════════════════════════════
    (frozenset(["quantum","mechanics","wave","function","schrodinger"]),
     _r("DEGREE", _DEG4, "B.Sc", "Physics", "Quantum Mechanics")),
    (frozenset(["nuclear","physics","degree","bsc","radioactive"]),
     _r("DEGREE", _DEG4, "B.Sc", "Physics", "Nuclear Physics")),
    (frozenset(["electrodynamics","maxwell","equations","degree"]),
     _r("DEGREE", _DEG4, "B.Sc", "Physics", "Electrodynamics")),
    (frozenset(["organic","reaction","mechanism","degree","bsc"]),
     _r("DEGREE", _DEG4, "B.Sc", "Chemistry", "Organic Reaction Mechanisms")),
    (frozenset(["stereochemistry","chirality","enantiomer","degree"]),
     _r("DEGREE", _DEG4, "B.Sc", "Chemistry", "Stereochemistry")),
    (frozenset(["abstract","algebra","group","ring","field"]),
     _r("DEGREE", _DEG4, "B.Sc", "Mathematics", "Abstract Algebra — Groups")),
    (frozenset(["real","analysis","sequence","series","convergence"]),
     _r("DEGREE", _DEG4, "B.Sc", "Mathematics", "Real Analysis")),
    (frozenset(["java","oops","degree","bsc","computer"]),
     _r("DEGREE", _DEG4, "B.Sc", "Computer Science", "Java Programming Fundamentals")),
    (frozenset(["dbms","database","normalization","sql","degree"]),
     _r("DEGREE", _DEG4, "B.Sc", "Computer Science", "Database Management Systems")),
    (frozenset(["data","structures","linked","list","tree","graph"]),
     _r("DEGREE", _DEG2, "B.Sc", "Computer Science", "Data Structures")),
    (frozenset(["c","programming","pointer","function","array","degree"]),
     _r("DEGREE", _DEG2, "B.Sc", "Computer Science", "Introduction to C Programming")),
    (frozenset(["calculus","degree","bsc","differentiation","integration"]),
     _r("DEGREE", _DEG2, "B.Sc", "Mathematics", "Differential Calculus")),
    (frozenset(["differential","equations","degree","bsc","ordinary"]),
     _r("DEGREE", _DEG2, "B.Sc", "Mathematics", "Differential Equations")),
    (frozenset(["mechanics","degree","bsc","rigid","body","rotation"]),
     _r("DEGREE", _DEG2, "B.Sc", "Physics", "Mechanics")),
    (frozenset(["thermodynamics","degree","bsc","carnot","entropy"]),
     _r("DEGREE", _DEG2, "B.Sc", "Physics", "Heat and Thermodynamics")),

    # ══════════════════════════════════════════════════════════════════════════
    # SEBA — Class 9 & 10  (General subjects)
    # ══════════════════════════════════════════════════════════════════════════
    (frozenset(["class","9","science","matter","atom"]),
     _r("SEBA", _SB9, "General", "Science", "Matter in Our Surroundings")),
    (frozenset(["class","10","science","chemical","reactions"]),
     _r("SEBA", _SB10, "General", "Science", "Chemical Reactions and Equations")),
    (frozenset(["class","10","electricity","ohm","seba"]),
     _r("SEBA", _SB10, "General", "Science", "Electricity")),
    (frozenset(["class","10","light","reflection","refraction","seba"]),
     _r("SEBA", _SB10, "General", "Science", "Light — Reflection and Refraction")),
    (frozenset(["class","10","carbon","compounds","organic"]),
     _r("SEBA", _SB10, "General", "Science", "Carbon and its Compounds")),
    (frozenset(["class","9","10","social","science","democracy","india"]),
     _r("SEBA", _SB10, "General", "Social Science", "Democratic Politics")),
    (frozenset(["class","9","10","economics","seba","poverty","development"]),
     _r("SEBA", _SB10, "General", "Social Science", "Understanding Economic Development")),
    (frozenset(["class","10","history","nationalism","india"]),
     _r("SEBA", _SB10, "General", "Social Science", "The Rise of Nationalism in Europe")),
    (frozenset(["class","9","mathematics","triangles","geometry"]),
     _r("SEBA", _SB9, "General", "Mathematics", "Triangles")),
    (frozenset(["class","10","mathematics","quadratic","equation"]),
     _r("SEBA", _SB10, "General", "Mathematics", "Quadratic Equations")),
    (frozenset(["class","10","mathematics","trigonometry","seba"]),
     _r("SEBA", _SB10, "General", "Mathematics", "Introduction to Trigonometry")),
    (frozenset(["class","10","arithmetic","progression","seba"]),
     _r("SEBA", _SB10, "General", "Mathematics", "Arithmetic Progressions")),
    (frozenset(["assam","history","culture","class","9","10"]),
     _r("SEBA", _SB10, "General", "Assamese", "Assam History and Culture")),
]

# ──────────────────────────────────────────────────────────────────────────────
# Normalised keyword set for partial scoring
# ──────────────────────────────────────────────────────────────────────────────

# Build subject → list[frozenset] for partial matching
_SUBJECT_KEYWORD_GROUPS: dict[str, list[frozenset]] = {}
for _kw_set, _route in KEYWORD_ROUTES:
    key = _route.subject
    _SUBJECT_KEYWORD_GROUPS.setdefault(key, []).append(_kw_set)

# All unique subjects in router
ALL_SUBJECTS = sorted(set(r.subject for _, r in KEYWORD_ROUTES))
ALL_BOARDS   = ["AHSEC", "SEBA", "DEGREE"]

# LLM subject list (concise, for token efficiency)
_LLM_SUBJECT_LIST = "\n".join(f"- {s}" for s in ALL_SUBJECTS)

# ──────────────────────────────────────────────────────────────────────────────
# Tier-1: Exact keyword match  (<5 ms)
# ──────────────────────────────────────────────────────────────────────────────

def _tokenise(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _exact_match(tokens: set[str]) -> Optional[SubjectRoute]:
    for kw_set, route in KEYWORD_ROUTES:
        if kw_set.issubset(tokens):
            return route
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Tier-2: Scored partial match  (<20 ms)
# ──────────────────────────────────────────────────────────────────────────────

def _partial_match(tokens: set[str]) -> Optional[SubjectRoute]:
    best_score = 0
    best_route: Optional[SubjectRoute] = None

    for kw_set, route in KEYWORD_ROUTES:
        matched = len(kw_set & tokens)
        total   = len(kw_set)
        if total == 0:
            continue
        score = matched / total
        if matched >= 2 and score > best_score:
            best_score = score
            best_route = route

    if best_route and best_score >= 0.60:
        best_route.confidence = "medium"
        return best_route
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Tier-3: LLM micro-classify  (~100 ms, ~50 tokens)
# Accepts an optional async llm_fn(prompt) → str to avoid circular imports.
# ──────────────────────────────────────────────────────────────────────────────

async def _llm_classify(
    query: str,
    llm_fn: Optional[Callable[[str], Awaitable[str]]] = None,
) -> Optional[SubjectRoute]:
    if llm_fn is None:
        return None
    try:
        prompt = (
            f"A student asked: \"{query}\"\n\n"
            f"Which AssamBoard subject does this question belong to?\n"
            f"Reply with ONLY the exact subject name from this list (no explanation):\n"
            f"{_LLM_SUBJECT_LIST}\n\n"
            f"If none match, reply: Unknown"
        )
        response = await asyncio.wait_for(llm_fn(prompt), timeout=4.0)
        subject_name = (response or "").strip().strip(".-").strip()
        for _, route in KEYWORD_ROUTES:
            if route.subject.lower() == subject_name.lower():
                route.confidence = "low"
                return route
    except Exception as exc:
        logger.warning(f"LLM subject classify failed: {exc}")
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def classify_subject_sync(query: str) -> Optional[SubjectRoute]:
    """
    Fast synchronous classification (Tier 1 + Tier 2 only).
    No DB or LLM call — safe to call from sync context.
    """
    tokens = _tokenise(query)
    return _exact_match(tokens) or _partial_match(tokens)


async def classify_subject(
    query: str,
    board_hint: str = "",
    class_hint: str = "",
    subject_hint: str = "",
    embedder=None,    # SyllabusEmbedder instance (Tier 0)
    llm_fn: Optional[Callable[[str], Awaitable[str]]] = None,  # Tier 3
) -> Optional[SubjectRoute]:
    """
    Full four-tier subject classifier.

    Tier 0 — Syllabus DB vector search (live, highest accuracy)
    Tier 1 — Exact keyword match (fast, offline)
    Tier 2 — Scored partial keyword match
    Tier 3 — LLM micro-classify via llm_fn callback

    Args:
        query        — raw user query string
        board_hint   — known board from user profile (AHSEC / SEBA / DEGREE)
        class_hint   — known class from user profile
        subject_hint — already-known subject name (skips classification)
        embedder     — SyllabusEmbedder instance (optional, enables Tier 0)
        llm_fn       — async callable(prompt) → str (optional, enables Tier 3)
    """
    # Shortcut: caller already knows the subject
    if subject_hint:
        route = SubjectRoute(
            board=board_hint or "AHSEC",
            class_name=class_hint or "",
            stream="",
            subject=subject_hint,
            confidence="high",
        )
        return route.build_scope(query)

    tokens = _tokenise(query)

    # Tier 0 — Syllabus DB vector search (highest accuracy, uses live embeddings)
    if embedder is not None:
        try:
            match = await asyncio.wait_for(embedder.classify(query), timeout=3.0)
            if match:
                route = SubjectRoute(
                    board=match.board,
                    class_name=match.class_name,
                    stream=match.stream,
                    subject=match.subject_name,
                    chapter_hint=match.chapter_title,
                    confidence="high",
                )
                logger.debug(
                    f"SubjectRouter Tier0 DB: {route.subject} / {route.chapter_hint} "
                    f"(sim={match.similarity}) | query: {query[:50]}"
                )
                return route.build_scope(query)
        except Exception as exc:
            logger.warning(f"SubjectRouter Tier0 failed: {exc}")

    # Tier 1 — exact keyword match
    route = _exact_match(tokens)
    if route:
        logger.debug(f"SubjectRouter Tier1: {route.subject} | query: {query[:50]}")
        return route.build_scope(query)

    # Tier 2 — partial keyword scoring
    route = _partial_match(tokens)
    if route:
        logger.debug(f"SubjectRouter Tier2: {route.subject} ({route.confidence}) | query: {query[:50]}")
        return route.build_scope(query)

    # Tier 3 — LLM micro-classify
    route = await _llm_classify(query, llm_fn)
    if route:
        logger.debug(f"SubjectRouter Tier3 LLM: {route.subject} | query: {query[:50]}")
        return route.build_scope(query)

    logger.info(f"SubjectRouter: no match | query: {query[:60]}")
    return None


async def build_search_scope(
    query: str,
    board_name: str = "",
    class_name: str = "",
    subject_name: str = "",
    embedder=None,
    llm_fn: Optional[Callable[[str], Awaitable[str]]] = None,
) -> tuple[str, Optional[SubjectRoute]]:
    """
    Returns (scoped_query_string, SubjectRoute | None).
    The scoped query is the base-layer web search query with curriculum context.
    Falls back to a simple board+class+subject prefix if no route found.
    """
    route = await classify_subject(
        query,
        board_hint=board_name,
        class_hint=class_name,
        subject_hint=subject_name,
        embedder=embedder,
        llm_fn=llm_fn,
    )
    if route:
        scoped = route.scope_query or route.build_scope(query).scope_query
    else:
        parts = [p for p in [board_name, class_name, subject_name, query] if p]
        scoped = " ".join(parts)

    return scoped, route

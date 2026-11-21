import os
import re
import secrets
import sqlite3
import shutil

DB_PATH = "/root/tg-drive/drive.db"
BACKUP_PATH = "/root/tg-drive/drive.db.backup_before_rearrange"

if not os.path.exists(DB_PATH):
    # Fallback to local drive.db if running locally
    if os.path.exists("drive.db"):
        DB_PATH = "drive.db"
        BACKUP_PATH = "drive.db.backup_before_rearrange"
    else:
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

print(f"[+] Creating backup of {DB_PATH} -> {BACKUP_PATH}...")
shutil.copy2(DB_PATH, BACKUP_PATH)
print("[+] Backup created successfully.")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

BASE_PATH = "/@gouravpwx/Lakshya_JEE_2026"

RULES = [
    # --- TESTS, NOTICES, PLANNERS, GUIDANCE ---
    ("Tests & Guidance", "Batch Notices & Banners", [r"^photo_\d+\.jpg$", r"master ncert with ai"]),
    ("Tests & Guidance", "Planners & Schedules", [r"lecture planner", r"test planner", r"class schedule", r"updated class schedule", r"telegram group"]),
    ("Tests & Guidance", "All India Test Series (AITS)", [r"\baits\b"]),
    ("Tests & Guidance", "Mock & Practice Tests", [r"mock test", r"practice test", r"advance practice test", r"board pattern test", r"replica test", r"test series", r"test schedule", r"test result", r"test analysis", r"mock paper", r"\bfst\b", r"full syllabus test"]),
    ("Tests & Guidance", "Contests & Events", [r"kaun banega champion", r"contest"]),
    ("Tests & Guidance", "Platform Announcements & Tutorials", [r"new update", r"new feature update", r"dark mode", r"kt video", r"audio mode", r"chat template", r"notes feature"]),
    ("Tests & Guidance", "Guidance & Mentorship", [r"guidance session", r"interaction session", r"orientation", r"podcast", r"how to", r"strategy", r"mentor", r"demo lecture", r"kbc special", r"form filling", r"faisal sir", r"rajwant sir", r"sachin sir", r"ashish sir", r"rohit sir"]),
    ("Tests & Guidance", "Assignments & Doubt Sessions", [r"revision question bank", r"assignment\s*:\s*\d+", r"\bdkd\b"]),
    ("Tests & Guidance", "Special Revision & Discussion Sessions", [r"jee advanced discussion", r"question practice in 20 minutes", r"mic session", r"mip session", r"advance session", r"summary lecture", r"homework discussion", r"one shot", r"discussion class", r"ncert discussion\s*\d+"]),
    ("Tests & Guidance", "NCERT & Formula Sheets", [r"complete xii", r"formula sheet"]),
    ("Tests & Guidance", "General 11th Revision", [r"11th revision"]),

    # --- PHYSICS ---
    ("Physics", "Electric Charges and Fields", [r"electric charges? and fields?", r"electric charge", r"coulomb"]),
    ("Physics", "Electrostatic Potential & Capacitance", [r"electrostatic potential", r"electric potential", r"\bcapacitance\b", r"\bcapacitors?\b", r"electrostatic", r"\bdipole\b"]),
    ("Physics", "Current Electricity", [r"current electricity", r"\bcurrent\b", r"potentiometer", r"meter bridge", r"kirchhoff"]),
    ("Physics", "Moving Charges and Magnetism", [r"moving charges?", r"magnetic effect", r"biot savart", r"ampere", r"lorentz", r"cyclotron"]),
    ("Physics", "Magnetism and Matter", [r"magnetism\s*(?:&|and)\s*matter", r"magnetic properties", r"earth magnetism"]),
    ("Physics", "Electromagnetic Induction", [r"electromagnetic induction", r"\Semi\b", r"faraday", r"lenz\x27?s law", r"inductance"]),
    ("Physics", "Alternating Current", [r"alternating current", r"\bac\b", r"lcr circuit", r"resonance"]),
    ("Physics", "Electromagnetic Waves", [r"electromagnetic waves?", r"\semw\b", r"displacement current"]),
    ("Physics", "Ray Optics & Optical Instruments", [r"ray optics", r"optical instruments?", r"reflection", r"refraction", r"prism", r"microscope", r"telescope", r"lens"]),
    ("Physics", "Wave Optics", [r"wave optics", r"interference", r"diffraction", r"polarisation", r"ydse", r"huygens"]),
    ("Physics", "Dual Nature of Radiation & Matter", [r"dual nature", r"photoelectric", r"matter waves?", r"de broglie"]),
    ("Physics", "Atoms", [r"\batoms?\b", r"atomic physics", r"bohr\x27?s model", r"hydrogen spectrum"]),
    ("Physics", "Nuclei", [r"\bnuclei\b", r"nuclear physics", r"radioactivity", r"mass defect", r"nuclear binding"]),
    ("Physics", "Semiconductor Electronics", [r"semiconductors?", r"p-n junction", r"diode", r"logic gates?"]),
    ("Physics", "Communication Systems", [r"communication systems?"]),
    ("Physics", "Modern Physics Revision", [r"modern physics"]),
    # Physics Class 11 Revision
    ("Physics", "Units, Measurements & Instruments", [r"units and dimensions?", r"instruments?", r"screw gauge", r"vernier", r"error analysis"]),
    ("Physics", "Kinematics (1D & 2D)", [r"motion in a straight line", r"motion in a plane", r"motion in 1d", r"motion in 2d", r"kinematics", r"projectile", r"relative velocity"]),
    ("Physics", "Laws of Motion & Friction", [r"laws of motion", r"newton[’\x27]?s laws?", r"\bnlm\b", r"\bfriction\b", r"pseudo force"]),
    ("Physics", "Work, Energy & Power", [r"work\s*,?\s*(?:power|energy)", r"work energy", r"\bwep\b"]),
    ("Physics", "Circular Motion", [r"circular motion", r"centripetal"]),
    ("Physics", "Centre of Mass & Collisions", [r"centre of mass", r"center of mass", r"\bcom\b", r"collisions?"]),
    ("Physics", "Rotational Motion", [r"rotational motion", r"moment of inertia", r"rigid body", r"rolling motion"]),
    ("Physics", "Gravitation", [r"gravitation", r"kepler\x27?s laws?"]),
    ("Physics", "Mechanical Properties of Solids & Fluids", [r"properties of solids?", r"elasticity", r"fluids?", r"mechanical properties", r"viscosity", r"bernoulli", r"surface tension"]),
    ("Physics", "Thermal Physics & Thermodynamics", [r"thermal properties", r"thermal expansion", r"calorimetry", r"heat transfer", r"kinetic theory", r"thermodynamics and kinetic", r"\bktg\b", r"thermodynamics"]),
    ("Physics", "Oscillations & Waves", [r"simple harmonic", r"\bshm\b", r"oscillations?", r"waves motion", r"sound waves?"]),
    ("Physics", "Basic Mathematics (Physics)", [r"11th basic revision", r"dot product", r"cross product"]),

    # --- MATHEMATICS ---
    ("Mathematics", "Relations and Functions", [r"relations?\s*(?:and|&)\s*functions?", r"\bfunctions?\b", r"\brelations?\b", r"set theory and relations"]),
    ("Mathematics", "Inverse Trigonometric Functions", [r"inverse trigonometric?", r"inverse trigonometry", r"\bitf\b"]),
    ("Mathematics", "Matrices", [r"matrices", r"\bmatrix\b"]),
    ("Mathematics", "Determinants", [r"determinants?"]),
    ("Mathematics", "Continuity & Differentiability", [r"continuity", r"differentiability", r"limit,\s*continuity"]),
    ("Mathematics", "Methods of Differentiation", [r"methods? of differentiation", r"differentiation\b"]),
    ("Mathematics", "Application of Derivatives (AOD)", [r"application of derivatives", r"\baod\b", r"tangents? and normals?", r"maxima and minima", r"monotonicity", r"rate measure"]),
    ("Mathematics", "Indefinite Integration", [r"indefinite integration", r"\bintegrals?\b"]),
    ("Mathematics", "Definite Integration", [r"definite integration", r"differente integration", r"definite integral"]),
    ("Mathematics", "Application of Integrals (AUC)", [r"application of integrals?", r"area under curves?", r"\bauc\b"]),
    ("Mathematics", "Differential Equations", [r"differential equations?"]),
    ("Mathematics", "Vector Algebra", [r"vector algebra", r"vectors? algebra", r"\bvectors?\b", r"vector and calculus"]),
    ("Mathematics", "Three Dimensional Geometry (3D)", [r"three dimensional coordinate geometry", r"three dimensional geometry", r"three dimension geometry", r"3d geometry", r"\b3d\b"]),
    ("Mathematics", "Probability", [r"probability", r"bayes theorem", r"random variable"]),
    ("Mathematics", "Linear Programming", [r"linear programming", r"\blpp\b"]),
    # Maths Class 11 Revision
    ("Mathematics", "Sets and Relations", [r"\bsets\b", r"basic maths and set theory"]),
    ("Mathematics", "Basic Mathematics & Logarithm", [r"basic mathematics", r"logarithm", r"modulus", r"inequalit(?:y|ies)"]),
    ("Mathematics", "Quadratic Equations", [r"quadratic equations?", r"polynomial", r"roots of unity"]),
    ("Mathematics", "Complex Numbers", [r"complex numbers?"]),
    ("Mathematics", "Sequences and Series", [r"sequences?\s*(?:&|and)\s*series", r"arithmetic progression", r"geometric progression", r"am-gm-hm", r"\bprogression\b"]),
    ("Mathematics", "Permutations and Combinations", [r"permutation", r"combinations?"]),
    ("Mathematics", "Binomial Theorem", [r"binomial theorem", r"\bbinomial\b"]),
    ("Mathematics", "Trigonometry", [r"trigonometr(?:y|ic)", r"heights? and distances?"]),
    ("Mathematics", "Straight Lines & Circles", [r"straight lines?", r"circles?"]),
    ("Mathematics", "Conic Sections", [r"conic sections?", r"parabola", r"ellipse", r"hyperbola"]),
    ("Mathematics", "Limits", [r"\blimits?\b"]),
    ("Mathematics", "Statistics & Mathematical Reasoning", [r"statistics", r"mathematical reasoning"]),

    # --- CHEMISTRY ---
    ("Chemistry", "Solid State", [r"solid state"]),
    ("Chemistry", "Solutions", [r"solutions?", r"colligative"]),
    ("Chemistry", "Electrochemistry", [r"electrochemistry", r"nernst equation", r"conductance"]),
    ("Chemistry", "Chemical Kinetics", [r"chemical kinetics", r"order of reaction", r"rate constant"]),
    ("Chemistry", "Surface Chemistry", [r"surface chemistry", r"adsorption", r"colloids?"]),
    ("Chemistry", "General Principles of Metallurgy", [r"metallurgy", r"isolation of metals", r"principles and processes of isolation"]),
    ("Chemistry", "The p-Block Elements", [r"p[- ]block", r"group 15", r"group 16", r"group 17", r"group 18"]),
    ("Chemistry", "The d & f-Block Elements", [r"d\s*(?:and|&)\s*f[- ]block", r"\bd block\b", r"\bf block\b"]),
    ("Chemistry", "Coordination Compounds", [r"coordination compounds?", r"isomerism in coordination", r"werner\x27?s theory", r"cft\b", r"vbt\b"]),
    ("Chemistry", "Qualitative Analysis (Salt Analysis)", [r"qualitative analysis", r"salt analysis"]),
    ("Chemistry", "Haloalkanes and Haloarenes", [r"haloalkanes?", r"haloarenes?", r"alkyl halides?", r"substitution and elimination", r"sn & e", r"application of sn", r"elimination"]),
    ("Chemistry", "Alcohols, Phenols and Ethers", [r"alcohols?,\s*phenols?", r"\balcohols?\b", r"\bphenols?\b", r"ethers?"]),
    ("Chemistry", "Aldehydes, Ketones & Carboxylic Acids", [r"aldehydes?,\s*ketones?", r"carboxylic acids?", r"acyl.*chloride", r"esters?", r"ketones?", r"nucleophilic addition"]),
    ("Chemistry", "Amines & Diazonium Salts", [r"\bamines?\b", r"diazonium"]),
    ("Chemistry", "Biomolecules", [r"biomolecules?", r"carbohydrates?", r"proteins?", r"amino acids?", r"nucleic acids?"]),
    ("Chemistry", "Polymers", [r"polymers?"]),
    ("Chemistry", "Chemistry in Everyday Life", [r"chemistry in everyday life"]),
    # Chemistry Class 11 Revision
    ("Chemistry", "Some Basic Concepts of Chemistry (Mole Concept)", [r"some basic concepts of chemistry", r"mole concept", r"stoichiometry"]),
    ("Chemistry", "Structure of Atom", [r"structure of atom", r"atomic structure"]),
    ("Chemistry", "Classification of Elements & Periodicity", [r"periodic classification", r"periodicity", r"periodic table", r"periodic properties"]),
    ("Chemistry", "Chemical Bonding & Molecular Structure", [r"chemical bonding", r"hybridisation", r"mot\b", r"dipole moment"]),
    ("Chemistry", "States of Matter", [r"states of matter", r"gaseous state", r"ideal gas"]),
    ("Chemistry", "Chemical Thermodynamics & Energetics", [r"chemical thermodynamics", r"thermochemistry", r"enthalpy", r"entropy"]),
    ("Chemistry", "Equilibrium (Chemical & Ionic)", [r"chemical equilibrium", r"ionic equilibrium", r"\bequilibrium\b"]),
    ("Chemistry", "Redox Reactions", [r"redox reactions?", r"oxidation number", r"reduction and oxidation"]),
    ("Chemistry", "General Organic Chemistry & Isomerism", [r"organic chemistry-some basic", r"general organic chemistry", r"\bgoc\b", r"isomerism", r"optical isomerism", r"geometrical isomer", r"iupac", r"resonance effect", r"inductive effect", r"hyperconjugation", r"carbene", r"nitrene", r"carbocation", r"free radical", r"heating effect", r"grignard", r"eas question"]),
    ("Chemistry", "Hydrocarbons", [r"hydrocarbons?", r"alkanes?", r"alkenes?", r"alkynes?", r"aromatic hydrocarbon", r"hydrogenation"]),
    ("Chemistry", "Environmental Chemistry", [r"environmental chemistry"])
]

# Fetch all files under Lakshya_JEE_2026
c.execute("SELECT id, name, folder FROM files WHERE folder = ? OR folder LIKE ?", (BASE_PATH, BASE_PATH + "/%"))
files = c.fetchall()
print(f"[+] Total files to arrange in Lakshya JEE: {len(files)}")

folder_set = set()
updated_count = 0

for file_id, file_name, old_folder in files:
    name_clean = file_name.lower()
    chosen_subject = "Tests & Guidance"
    chosen_chapter = "General Materials"

    for subject, chapter, patterns in RULES:
        if any(re.search(p, name_clean) for p in patterns):
            chosen_subject = subject
            chosen_chapter = chapter
            break

    new_folder = f"{BASE_PATH}/{chosen_subject}/{chosen_chapter}"
    folder_set.add(f"{BASE_PATH}/{chosen_subject}")
    folder_set.add(new_folder)

    c.execute("UPDATE files SET folder = ? WHERE id = ?", (new_folder, file_id))
    updated_count += 1

# Register all folders in folders table with share tokens
c.execute("SELECT path FROM folders")
existing_paths = {row[0] for row in c.fetchall()}

folders_added = 0
for fpath in folder_set:
    if fpath not in existing_paths:
        c.execute("INSERT OR IGNORE INTO folders (path, share_token) VALUES (?, ?)", 
                  (fpath, secrets.token_urlsafe(14)))
        folders_added += 1

conn.commit()
conn.close()

print(f"[+] Successfully rearranged {updated_count} files into Subject -> Chapter hierarchy!")
print(f"[+] Created {folders_added} new subject/chapter folder entries in database.")

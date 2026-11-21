import os
import re
import secrets
import sqlite3
import shutil

DB_PATH = "/root/tg-drive/drive.db"
BACKUP_PATH = "/root/tg-drive/drive.db.backup_before_exact_rearrange"

if not os.path.exists(DB_PATH):
    if os.path.exists("drive.db"):
        DB_PATH = "drive.db"
        BACKUP_PATH = "drive.db.backup_before_exact_rearrange"
    else:
        raise FileNotFoundError(f"Database not found at {DB_PATH}")

print(f"[+] Creating backup: {DB_PATH} -> {BACKUP_PATH}...")
shutil.copy2(DB_PATH, BACKUP_PATH)
print("[+] Backup created.")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

BASE_PATH = "/@gouravpwx/Lakshya_JEE_2026"

PREFIX_MAP = {
    # --- PHYSICS ---
    "electric charges and fields": ("Physics", "Electric Charges and Fields"),
    "electric charges & fields": ("Physics", "Electric Charges and Fields"),
    "electric charge": ("Physics", "Electric Charges and Fields"),
    "electrostatic": ("Physics", "Electrostatic Potential and Capacitance"),
    "electrostatic potential and capacitance": ("Physics", "Electrostatic Potential and Capacitance"),
    "electric potential and dipole": ("Physics", "Electrostatic Potential and Capacitance"),
    "capacitance": ("Physics", "Electrostatic Potential and Capacitance"),
    "current electricity": ("Physics", "Current Electricity"),
    "moving charges and magnetism": ("Physics", "Moving Charges and Magnetism"),
    "moving charges & magnetism": ("Physics", "Moving Charges and Magnetism"),
    "magnetism and matter": ("Physics", "Magnetism and Matter"),
    "magnetism & matter": ("Physics", "Magnetism and Matter"),
    "electromagnetic induction": ("Physics", "Electromagnetic Induction"),
    "alternating current": ("Physics", "Alternating Current"),
    "electromagnetic waves": ("Physics", "Electromagnetic Waves"),
    "ray optics and optical instruments": ("Physics", "Ray Optics and Optical Instruments"),
    "ray optics": ("Physics", "Ray Optics and Optical Instruments"),
    "wave optics": ("Physics", "Wave Optics"),
    "dual nature of radiation and matter": ("Physics", "Dual Nature of Radiation and Matter"),
    "dual nature of  radiation and matter": ("Physics", "Dual Nature of Radiation and Matter"),
    "dual nature of matter & radiation": ("Physics", "Dual Nature of Radiation and Matter"),
    "atoms": ("Physics", "Atoms"),
    "atomic physics": ("Physics", "Atoms"),
    "nuclei": ("Physics", "Nuclei"),
    "nuclear physics": ("Physics", "Nuclei"),
    "semiconductors": ("Physics", "Semiconductor Electronics"),
    "semiconductor": ("Physics", "Semiconductor Electronics"),
    "semiconductor electronics": ("Physics", "Semiconductor Electronics"),
    "communication systems": ("Physics", "Communication Systems"),
    "modern physics": ("Physics", "Modern Physics Revision"),
    "units and dimensions": ("Physics", "Units, Dimensions & Instruments"),
    "instruments": ("Physics", "Units, Dimensions & Instruments"),
    "motion in a straight line": ("Physics", "Motion in a Straight Line (1D)"),
    "motion in a plane": ("Physics", "Motion in a Plane (2D & Projectile)"),
    "motion in 2d": ("Physics", "Motion in a Plane (2D & Projectile)"),
    "laws of motion": ("Physics", "Laws of Motion & Friction"),
    "newton’s laws of motion": ("Physics", "Laws of Motion & Friction"),
    "newton\x27s law of motion": ("Physics", "Laws of Motion & Friction"),
    "friction": ("Physics", "Laws of Motion & Friction"),
    "work energy power": ("Physics", "Work, Power and Energy"),
    "work, power and energy": ("Physics", "Work, Power and Energy"),
    "circular motion": ("Physics", "Circular Motion"),
    "centre of mass": ("Physics", "Centre of Mass & Collisions"),
    "motion of system of particle and com": ("Physics", "Centre of Mass & Collisions"),
    "rotational motion": ("Physics", "Rotational Motion"),
    "gravitation": ("Physics", "Gravitation"),
    "properties of solids": ("Physics", "Mechanical Properties of Solids & Fluids"),
    "mechanical properties of  solids and fluids": ("Physics", "Mechanical Properties of Solids & Fluids"),
    "thermal properties of matter": ("Physics", "Thermal Properties of Matter & Thermodynamics"),
    "thermodynamics and kinetic theory of gases": ("Physics", "Thermal Properties of Matter & Thermodynamics"),
    "waves motion": ("Physics", "Thermal Properties of Matter & Thermodynamics"),
    "simple harmonic motion": ("Physics", "Thermal Properties of Matter & Thermodynamics"),
    "11th basic revision": ("Physics", "Basic Revision & Vectors (Physics)"),
    "dot product": ("Physics", "Basic Revision & Vectors (Physics)"),
    "vector and calculus": ("Physics", "Basic Revision & Vectors (Physics)"),
    "physics catalyst": ("Physics", "Basic Revision & Vectors (Physics)"),

    # --- CHEMISTRY ---
    "solid state": ("Chemistry", "Solid State"),
    "the solid state": ("Chemistry", "Solid State"),
    "solutions": ("Chemistry", "Solutions"),
    "solution": ("Chemistry", "Solutions"),
    "electrochemistry": ("Chemistry", "Electrochemistry"),
    "chemical kinetics": ("Chemistry", "Chemical Kinetics"),
    "surface chemistry": ("Chemistry", "Surface Chemistry"),
    "general principles and processes of isolation of metals": ("Chemistry", "General Principles & Metallurgy"),
    "metallurgy": ("Chemistry", "General Principles & Metallurgy"),
    "the p-block elements": ("Chemistry", "The p-Block Elements"),
    "p-block": ("Chemistry", "The p-Block Elements"),
    "p block element": ("Chemistry", "The p-Block Elements"),
    "the d and f-block elements": ("Chemistry", "The d and f-Block Elements"),
    "d & f block": ("Chemistry", "The d and f-Block Elements"),
    "d & f blocks elements": ("Chemistry", "The d and f-Block Elements"),
    "d block": ("Chemistry", "The d and f-Block Elements"),
    "f block": ("Chemistry", "The d and f-Block Elements"),
    "coordination compounds": ("Chemistry", "Coordination Compounds"),
    "coordination compound": ("Chemistry", "Coordination Compounds"),
    "principles of qualitative analysis": ("Chemistry", "Qualitative Analysis (Salt Analysis)"),
    "salt analysis": ("Chemistry", "Qualitative Analysis (Salt Analysis)"),
    "systematic qualitative analysis": ("Chemistry", "Qualitative Analysis (Salt Analysis)"),
    "haloalkanes and haloarenes": ("Chemistry", "Haloalkanes and Haloarenes"),
    "haloalkanes & haloarenes intext exercise": ("Chemistry", "Haloalkanes and Haloarenes"),
    "haloalkane": ("Chemistry", "Haloalkanes and Haloarenes"),
    "haloalkane and arene": ("Chemistry", "Haloalkanes and Haloarenes"),
    "sn haloalkane": ("Chemistry", "Haloalkanes and Haloarenes"),
    "sn & e": ("Chemistry", "Haloalkanes and Haloarenes"),
    "application of sn": ("Chemistry", "Haloalkanes and Haloarenes"),
    "elimination": ("Chemistry", "Haloalkanes and Haloarenes"),
    "eas question": ("Chemistry", "Haloalkanes and Haloarenes"),
    "eas solutions": ("Chemistry", "Haloalkanes and Haloarenes"),
    "substitution and elimination": ("Chemistry", "Haloalkanes and Haloarenes"),
    "alcohols, phenols and ethers": ("Chemistry", "Alcohols, Phenols and Ethers"),
    "alcohols, phenols and  ethers": ("Chemistry", "Alcohols, Phenols and Ethers"),
    "alcohol, phenol and ether": ("Chemistry", "Alcohols, Phenols and Ethers"),
    "alcohols": ("Chemistry", "Alcohols, Phenols and Ethers"),
    "alcohol": ("Chemistry", "Alcohols, Phenols and Ethers"),
    "phenol": ("Chemistry", "Alcohols, Phenols and Ethers"),
    "alcohols & ether": ("Chemistry", "Alcohols, Phenols and Ethers"),
    "aldehydes, ketones and carboxylic acids": ("Chemistry", "Aldehydes, Ketones and Carboxylic Acids"),
    "aldehydes, ketones and  carboxylic acids": ("Chemistry", "Aldehydes, Ketones and Carboxylic Acids"),
    "aldehydes ketones": ("Chemistry", "Aldehydes, Ketones and Carboxylic Acids"),
    "carboxylic acids": ("Chemistry", "Aldehydes, Ketones and Carboxylic Acids"),
    "ketones": ("Chemistry", "Aldehydes, Ketones and Carboxylic Acids"),
    "acyl (acid) chloride": ("Chemistry", "Aldehydes, Ketones and Carboxylic Acids"),
    "esters": ("Chemistry", "Aldehydes, Ketones and Carboxylic Acids"),
    "nucleophilic addition": ("Chemistry", "Aldehydes, Ketones and Carboxylic Acids"),
    "amines": ("Chemistry", "Amines & Diazonium Salts"),
    "amino acid": ("Chemistry", "Amines & Diazonium Salts"),
    "biomolecules": ("Chemistry", "Biomolecules"),
    "polymers": ("Chemistry", "Polymers"),
    "polymer": ("Chemistry", "Polymers"),
    "chemistry in everyday life": ("Chemistry", "Chemistry in Everyday Life"),
    "optical isomerism": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "isomerism": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "iupac": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "iupac nomenclature": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "goc": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "organic chemistry-some basic  principles and techniques": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "discussion class": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "heating effect": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "carbene and nitrene": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "grignard and mettalic hydride": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "carbocation and free radical": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "reduction and oxidation": ("Chemistry", "General Organic Chemistry & Isomerism"),
    "hydrocarbon": ("Chemistry", "Hydrocarbons"),
    "hydrocarbons": ("Chemistry", "Hydrocarbons"),
    "some basic concepts of chemistry": ("Chemistry", "Some Basic Concepts of Chemistry"),
    "structure of atom": ("Chemistry", "Structure of Atom"),
    "atomic structure": ("Chemistry", "Structure of Atom"),
    "classification of elements and periodicity in properties": ("Chemistry", "Classification of Elements & Periodicity"),
    "periodic classification": ("Chemistry", "Classification of Elements & Periodicity"),
    "chemical bonding and molecular structure": ("Chemistry", "Chemical Bonding and Molecular Structure"),
    "chemical equilibrium": ("Chemistry", "Equilibrium & Redox"),
    "equilibrium": ("Chemistry", "Equilibrium & Redox"),
    "redox reaction": ("Chemistry", "Equilibrium & Redox"),
    "redox reactions": ("Chemistry", "Equilibrium & Redox"),
    "thermodynamics": ("Chemistry", "Equilibrium & Redox"),

    # --- MATHEMATICS ---
    "relations and functions": ("Mathematics", "Relations and Functions"),
    "relations": ("Mathematics", "Relations and Functions"),
    "functions": ("Mathematics", "Relations and Functions"),
    "set theory and relations": ("Mathematics", "Relations and Functions"),
    "set and relations": ("Mathematics", "Relations and Functions"),
    "sets": ("Mathematics", "Relations and Functions"),
    "basic maths and set theory": ("Mathematics", "Relations and Functions"),
    "inverse trigonometric functions": ("Mathematics", "Inverse Trigonometric Functions"),
    "inverse trigonometry functions": ("Mathematics", "Inverse Trigonometric Functions"),
    "matrices": ("Mathematics", "Matrices"),
    "determinants": ("Mathematics", "Determinants"),
    "determinant": ("Mathematics", "Determinants"),
    "matrix and determinants": ("Mathematics", "Determinants"),
    "matrices and determinants": ("Mathematics", "Determinants"),
    "limit, continuity and differentiability": ("Mathematics", "Limit, Continuity and Differentiability"),
    "limit continuity and differentiability": ("Mathematics", "Limit, Continuity and Differentiability"),
    "limit , continuity and differentiability": ("Mathematics", "Limit, Continuity and Differentiability"),
    "continuity & differentiability": ("Mathematics", "Limit, Continuity and Differentiability"),
    "continuity and differentiability": ("Mathematics", "Limit, Continuity and Differentiability"),
    "continuity": ("Mathematics", "Limit, Continuity and Differentiability"),
    "differentiability": ("Mathematics", "Limit, Continuity and Differentiability"),
    "limit": ("Mathematics", "Limit, Continuity and Differentiability"),
    "limits": ("Mathematics", "Limit, Continuity and Differentiability"),
    "limits of functions": ("Mathematics", "Limit, Continuity and Differentiability"),
    "methods of differentiation": ("Mathematics", "Methods of Differentiation"),
    "method of differentiation": ("Mathematics", "Methods of Differentiation"),
    "differentiation": ("Mathematics", "Methods of Differentiation"),
    "continuity and differentiability, methods of differentiation": ("Mathematics", "Methods of Differentiation"),
    "application of derivatives": ("Mathematics", "Application of Derivatives (AOD)"),
    "apllication of derivatives": ("Mathematics", "Application of Derivatives (AOD)"),
    "aod and mod": ("Mathematics", "Application of Derivatives (AOD)"),
    "rate measure consolidation": ("Mathematics", "Application of Derivatives (AOD)"),
    "indefinite integration": ("Mathematics", "Indefinite Integration"),
    "integrals": ("Mathematics", "Indefinite Integration"),
    "definite integration": ("Mathematics", "Definite Integration"),
    "differente integration": ("Mathematics", "Definite Integration"),
    "definite integration and indefinite integration": ("Mathematics", "Definite Integration"),
    "definite integration & aoi": ("Mathematics", "Definite Integration"),
    "application of integrals": ("Mathematics", "Application of Integrals (AUC)"),
    "application of integral": ("Mathematics", "Application of Integrals (AUC)"),
    "area under curve": ("Mathematics", "Application of Integrals (AUC)"),
    "differential equation and area under curve": ("Mathematics", "Application of Integrals (AUC)"),
    "differential equations": ("Mathematics", "Differential Equations"),
    "differential equation": ("Mathematics", "Differential Equations"),
    "vector algebra": ("Mathematics", "Vector Algebra"),
    "vectors algebra": ("Mathematics", "Vector Algebra"),
    "vector": ("Mathematics", "Vector Algebra"),
    "three dimensional geometry": ("Mathematics", "Three Dimensional Geometry (3D)"),
    "three dimension geometry": ("Mathematics", "Three Dimensional Geometry (3D)"),
    "three dimensional coordinate geometry": ("Mathematics", "Three Dimensional Geometry (3D)"),
    "probability": ("Mathematics", "Probability"),
    "linear programming": ("Mathematics", "Linear Programming"),
    "sequence and series": ("Mathematics", "Sequences and Series"),
    "sequence & series": ("Mathematics", "Sequences and Series"),
    "permutation and combination": ("Mathematics", "Permutations and Combinations"),
    "permutations and combinations": ("Mathematics", "Permutations and Combinations"),
    "permutation combination": ("Mathematics", "Permutations and Combinations"),
    "binomial theorem": ("Mathematics", "Binomial Theorem"),
    "quadratic equation": ("Mathematics", "Quadratic Equations & Logarithm"),
    "quadratic equations": ("Mathematics", "Quadratic Equations & Logarithm"),
    "basic mathematics and logarithm": ("Mathematics", "Quadratic Equations & Logarithm"),
    "complex numbers": ("Mathematics", "Complex Numbers"),
    "straight line": ("Mathematics", "Straight Lines & Circles"),
    "straight lines": ("Mathematics", "Straight Lines & Circles"),
    "circle": ("Mathematics", "Straight Lines & Circles"),
    "circles": ("Mathematics", "Straight Lines & Circles"),
    "conic sections": ("Mathematics", "Conic Sections"),
    "conic section": ("Mathematics", "Conic Sections"),
    "parabola": ("Mathematics", "Conic Sections"),
    "ellipse": ("Mathematics", "Conic Sections"),
    "hyperbola": ("Mathematics", "Conic Sections"),
    "trigonometry": ("Mathematics", "Trigonometry"),
    "trigonometric ratios and identities": ("Mathematics", "Trigonometry"),
    "trigonometric functions & equations": ("Mathematics", "Trigonometry"),
    "statistics": ("Mathematics", "Statistics"),

    # --- TESTS & GUIDANCE ---
    "aits": ("Tests & Guidance", "All India Test Series (AITS)"),
    "aits 03 - paper": ("Tests & Guidance", "All India Test Series (AITS)"),
    "aits 07 to": ("Tests & Guidance", "All India Test Series (AITS)"),
    "practice test": ("Tests & Guidance", "Mock & Practice Tests"),
    "advance practice test": ("Tests & Guidance", "Mock & Practice Tests"),
    "jee main mock test": ("Tests & Guidance", "Mock & Practice Tests"),
    "board pattern test": ("Tests & Guidance", "Mock & Practice Tests"),
    "short practice test": ("Tests & Guidance", "Mock & Practice Tests"),
    "mock paper": ("Tests & Guidance", "Mock & Practice Tests"),
    "iit-jee mock & replica test": ("Tests & Guidance", "Mock & Practice Tests"),
    "mock and replica": ("Tests & Guidance", "Mock & Practice Tests"),
    "fst": ("Tests & Guidance", "Mock & Practice Tests"),
    "air admission": ("Tests & Guidance", "Mock & Practice Tests"),
    "guidance session": ("Tests & Guidance", "Guidance & Mentorship"),
    "live interaction session": ("Tests & Guidance", "Guidance & Mentorship"),
    "live interaction session by ashish sir  only video": ("Tests & Guidance", "Guidance & Mentorship"),
    "important session by faisal sir": ("Tests & Guidance", "Guidance & Mentorship"),
    "important session by rohit sir": ("Tests & Guidance", "Guidance & Mentorship"),
    "podcast": ("Tests & Guidance", "Guidance & Mentorship"),
    "interaction session": ("Tests & Guidance", "Guidance & Mentorship"),
    "how to use": ("Tests & Guidance", "Guidance & Mentorship"),
    "lecture planner": ("Tests & Guidance", "Batch Planners & Notices"),
    "lakshya jee": ("Tests & Guidance", "Batch Planners & Notices"),
    "kaun banega champion contest 2026 rules": ("Tests & Guidance", "Contests & Events"),
    "new feature update": ("Tests & Guidance", "Platform Updates & Tutorials"),
    "new update": ("Tests & Guidance", "Platform Updates & Tutorials"),
    "important update": ("Tests & Guidance", "Platform Updates & Tutorials"),
    "question practice in 20 minutes": ("Tests & Guidance", "Special Revision & Discussion Classes"),
    "advance session": ("Tests & Guidance", "Special Revision & Discussion Classes"),
    "homework discussion": ("Tests & Guidance", "Special Revision & Discussion Classes"),
    "ncert discussion": ("Tests & Guidance", "Special Revision & Discussion Classes"),
    "jee advanced discussion": ("Tests & Guidance", "Special Revision & Discussion Classes"),
    "revision question bank": ("Tests & Guidance", "Special Revision & Discussion Classes"),
    "assignment": ("Tests & Guidance", "Special Revision & Discussion Classes"),
    "complete xii": ("Tests & Guidance", "Special Revision & Discussion Classes"),
    "11th revision": ("Tests & Guidance", "11th General Revision"),
}

c.execute("SELECT id, name, folder FROM files WHERE folder = ? OR folder LIKE ?", (BASE_PATH, BASE_PATH + "/%"))
files = c.fetchall()
print(f"[+] Total files to re-classify in Lakshya JEE: {len(files)}")

folder_set = set()
updated_count = 0

for file_id, file_name, old_folder in files:
    parts = re.split(r"\s*:\s*", file_name, maxsplit=1)
    matched = False
    chosen_subject = "Tests & Guidance"
    chosen_chapter = "Special Revision & Discussion Classes"

    if len(parts) > 1:
        prefix = parts[0].strip().lower()
        clean_ch = re.sub(r"\s+\d+$", "", prefix).strip()
        clean_ch = re.sub(r"\s*\(.*?\)$", "", clean_ch).strip()
        clean_ch = re.sub(r"\s+\d+$", "", clean_ch).strip()

        if clean_ch in PREFIX_MAP:
            chosen_subject, chosen_chapter = PREFIX_MAP[clean_ch]
            matched = True
        else:
            for p, (s, ch) in PREFIX_MAP.items():
                if clean_ch.startswith(p) or p.startswith(clean_ch):
                    chosen_subject, chosen_chapter = s, ch
                    matched = True
                    break

    if not matched:
        nl = file_name.lower()
        if "kaun banega champion" in nl:
            chosen_subject, chosen_chapter = "Tests & Guidance", "Contests & Events"
        elif "dkd" in nl:
            chosen_subject, chosen_chapter = "Tests & Guidance", "Special Revision & Discussion Classes"
        elif "photo_" in nl or "master ncert" in nl:
            chosen_subject, chosen_chapter = "Tests & Guidance", "Batch Planners & Notices"
        elif any(w in nl for w in ["demo lecture", "how to", "live interaction", "important session", "form filling", "kbc special"]):
            chosen_subject, chosen_chapter = "Tests & Guidance", "Guidance & Mentorship"
        elif "kt video" in nl:
            chosen_subject, chosen_chapter = "Tests & Guidance", "Platform Updates & Tutorials"

    new_folder = f"{BASE_PATH}/{chosen_subject}/{chosen_chapter}"
    folder_set.add(f"{BASE_PATH}/{chosen_subject}")
    folder_set.add(new_folder)

    c.execute("UPDATE files SET folder = ? WHERE id = ?", (new_folder, file_id))
    updated_count += 1

# Register folder entries
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

print(f"[+] Exact classification successfully applied to {updated_count} files!")
print(f"[+] Registered {folders_added} folders in folders table.")

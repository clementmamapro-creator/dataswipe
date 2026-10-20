"""
skills_taxonomy.py

Liste curée des compétences reconnues par DataSwipe pour le scoring de
compatibilité CV/offre. Volontairement en dur (pas de NLP/ML ici) : le score
doit rester explicable — "vous avez 6 des 9 compétences demandées" est une
réponse compréhensible, contrairement à un score de similarité vectorielle.

Organisée par catégorie pour faciliter la maintenance et l'extension future.
Chaque entrée est la forme "canonique" (affichage) ; la détection dans le
texte est insensible à la casse et gère quelques variantes usuelles.
"""

SKILLS_TAXONOMY: dict[str, list[str]] = {
    "Langages": [
        "Python", "SQL", "R", "Java", "Scala", "C++", "C#", "JavaScript",
        "TypeScript", "Bash", "PySpark",
    ],
    "Data Engineering": [
        "Airflow", "Spark", "Kafka", "Hadoop", "dbt", "ETL", "ELT",
        "Talend", "Nifi", "Databricks", "Snowflake", "BigQuery",
        "Redshift", "DataOps",
    ],
    "Bases de données": [
        "PostgreSQL", "MySQL", "MongoDB", "Cassandra", "Redis",
        "Elasticsearch", "Oracle", "SQL Server", "SQLite", "Neo4j",
    ],
    "Cloud & Infra": [
        "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform",
        "CI/CD", "Jenkins", "GitLab CI", "GitHub Actions", "Linux",
    ],
    "Data Analyse & BI": [
        "Power BI", "Tableau", "Looker", "Excel", "Pandas", "NumPy",
        "DAX", "Google Data Studio", "Qlik", "Metabase",
    ],
    "Data Science & ML": [
        "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch",
        "Scikit-learn", "NLP", "Computer Vision", "MLOps", "Jupyter",
        "Statistiques",
    ],
    "Gestion de projet & Méthodo": [
        "Agile", "Scrum", "Kanban", "JIRA", "Confluence", "Gestion de projet",
        "MOA", "MOE", "Product Owner",
    ],
    "Autres": [
        "Git", "API REST", "GraphQL", "Data Governance", "RGPD",
        "Data Quality", "Data Modeling",
    ],
}

# Vue à plat, utilisée pour la détection dans un texte
ALL_SKILLS: list[str] = [
    skill for skills in SKILLS_TAXONOMY.values() for skill in skills
]

# Variantes / synonymes usuels -> forme canonique de la taxonomie.
# Complète, ne remplace pas ALL_SKILLS (la détection vérifie les deux).
SKILL_ALIASES: dict[str, str] = {
    "powerbi": "Power BI",
    "power-bi": "Power BI",
    "ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "postgres": "PostgreSQL",
    "k8s": "Kubernetes",
    "gcp": "GCP",
    "amazon web services": "AWS",
    "google cloud": "GCP",
    "microsoft azure": "Azure",
    "scikit learn": "Scikit-learn",
    "sklearn": "Scikit-learn",
    "ci cd": "CI/CD",
    "rest api": "API REST",
    "restful api": "API REST",
}

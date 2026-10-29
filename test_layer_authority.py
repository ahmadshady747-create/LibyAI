"""Guards for the layer boundaries documented in ARCHITECTURE.md.

These are not behavior tests for clinic features; they guard against
the specific regressions that made the dual layer confusing before:
dead code after a delegation return, and the two fuzzy finders silently
diverging on the same query.
"""

import ast
import os


def _statements_after_return(path, func_name):
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for i, stmt in enumerate(node.body):
                if isinstance(stmt, ast.Return) and i < len(node.body) - 1:
                    return node.body[i + 1 :]
    return []


def test_no_dead_code_after_delegation_returns():
    """Both authoritative delegators must end at their return.

    Before round 4, each of these functions had a large unreachable
    block after its return, which misled readers about which path
    actually runs. This test fails if such a block comes back.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    admin_path = os.path.join(here, "app", "services", "admin_processor.py")
    llm_path = os.path.join(here, "app", "services", "llm_service.py")
    assert _statements_after_return(admin_path, "process_authorized_staff_message") == []
    assert _statements_after_return(llm_path, "generate_patient_response") == []


def test_both_fuzzy_finders_agree_on_a_doctor_name():
    """Legacy and SQLModel finders must agree on the same doctor name.

    They return different types (dict vs SQLModel object) and use
    different scoring, so this checks the name, not the row id. The test
    inserts its own uniquely named, active doctor first, so it does not
    depend on which seeded doctors happen to be active in the shared DB.
    Before round 4, the SQLModel finder returned the first doctor sharing
    ANY keyword, so a distinctive name could return an unrelated doctor
    who merely shares a first name; its scoring now mirrors the legacy
    finder, and this test is the regression guard for that fix.
    """
    import db
    from sqlmodel import Session, select
    from app.database.models import Doctor
    from app.database.session import engine
    from app.services import db_service

    query = "اختبار التوحيد الفريد"
    with Session(engine) as session:
        for old in session.exec(
            select(Doctor).where(Doctor.name.contains(query))
        ).all():
            session.delete(old)
        session.add(Doctor(
            name=f"د. {query}",
            specialty="تخصص اختبار فريد",
            regular_schedule="يومياً",
            consultation_fee=40.0,
            is_active=True,
        ))
        session.commit()

    legacy = db.find_doctor_fuzzy(name_query=query, specialty_query=query)
    modern = db_service.find_doctor_fuzzy(name_query=query, specialty_query=query)
    assert legacy is not None, "Legacy finder found no doctor for the query"
    assert modern is not None, "SQLModel finder found no doctor for the query"
    assert query in legacy["name"], f"Legacy finder returned wrong doctor: {legacy['name']}"
    assert query in modern.name, f"SQLModel finder returned wrong doctor: {modern.name}"

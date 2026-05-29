from pathlib import Path
from sqlmodel import Session, select, delete
from src.domain.financial_account import FinancialAccountClassifier
from src.domain.party_normalize import PartyNormalizer
from src.domain.sampling import Sampler, SampledParty
from src.infrastructure.gl_loader import GLLoader
from src.infrastructure.db.repository import upsert_counterparty
from src.infrastructure.db.models import Counterparty, ExtractedRecord

ROOT = Path(__file__).resolve().parents[2]

def run_sampling(session: Session, project_id: int, gl_path: Path) -> list[SampledParty]:
    clf = FinancialAccountClassifier.load(ROOT / "configs" / "financial_keywords.yaml")
    norm = PartyNormalizer.load(ROOT / "configs")

    # 재실행 시 이전 sampling 결과 clear (garbage 누적 방지)
    session.exec(delete(ExtractedRecord).where(ExtractedRecord.project_id == project_id))
    session.exec(delete(Counterparty).where(Counterparty.project_id == project_id))
    session.commit()

    rows = list(GLLoader(gl_path).iter_rows())
    parties = Sampler(clf, norm).sample(rows)
    parties.sort(key=lambda p: (-p.bs_amount + -abs(p.pl_amount)))  # 큰 거래 우선 BC-1
    for sp in parties:
        c = upsert_counterparty(
            session, project_id,
            canonical_name=sp.party.canonical,
            branch=sp.party.branch,
            is_foreign=sp.party.is_foreign,
        )
        c.bs_balance = sp.bs_amount
        c.pl_volume = sp.pl_amount
        session.add(c)
    session.commit()
    return parties

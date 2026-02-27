"""Conflict of interest checking and management module."""

import logging
import re
from datetime import datetime
from difflib import SequenceMatcher
from uuid import uuid4

from thomas.legal._types import Conflict

logger = logging.getLogger(__name__)


class ConflictChecker:
    """Manages conflict checking and waiver management."""

    def __init__(self) -> None:
        """Initialize the conflict checker."""
        self.conflicts: dict[str, Conflict] = {}
        self.parties_index: dict[str, set[str]] = {}  # party_name -> case_ids
        self.waivers: dict[str, dict] = {}
        self.prior_matters: dict[str, list[dict]] = {}  # attorney_id -> matters

    def check_party_conflict(
        self,
        party_name: str,
        case_id: str,
    ) -> Conflict | None:
        """Check if party is involved in other cases (direct adverse).

        Uses fuzzy matching to handle name variations.
        """
        party_lower = party_name.lower()

        # Check existing parties using fuzzy matching
        for existing_party, case_ids in self.parties_index.items():
            similarity = self._fuzzy_match(party_lower, existing_party.lower())

            if similarity > 0.85:  # High confidence match
                # Check if any existing case is adverse
                for other_case_id in case_ids:
                    existing_conflict = Conflict(
                        conflict_id=str(uuid4()),
                        party_name=party_name,
                        case_id=case_id,
                        conflict_type="direct_adverse",
                        related_parties=[existing_party],
                        description=f"Party matches existing matter in case {other_case_id}",
                    )
                    return existing_conflict

        return None

    def check_material_limitation(
        self,
        attorney_id: str,
        party_name: str,
        case_id: str,
    ) -> Conflict | None:
        """Check for material limitation conflicts.

        Detects when attorney's interests in one matter could affect representation.
        """
        if attorney_id not in self.prior_matters:
            return None

        prior = self.prior_matters[attorney_id]

        for prior_matter in prior:
            # Check if same party involved in different capacity
            if self._fuzzy_match(party_name.lower(), prior_matter["party_name"].lower()) > 0.85:
                if prior_matter.get("is_adverse"):
                    return Conflict(
                        conflict_id=str(uuid4()),
                        party_name=party_name,
                        case_id=case_id,
                        conflict_type="material_limitation",
                        related_parties=[prior_matter["party_name"]],
                        description="Attorney has prior adverse interest with this party",
                    )

        return None

    def check_business_transaction_conflict(
        self,
        attorney_id: str,
        client_id: str,
        transaction_parties: list[str],
    ) -> Conflict | None:
        """Check for conflicts involving business transactions with clients.

        Firm or attorney should not be on opposite side of transaction.
        """
        if attorney_id in self.prior_matters:
            for matter in self.prior_matters[attorney_id]:
                for trans_party in transaction_parties:
                    if self._fuzzy_match(trans_party.lower(), matter["party_name"].lower()) > 0.85:
                        if matter.get("is_adverse"):
                            return Conflict(
                                conflict_id=str(uuid4()),
                                party_name=client_id,
                                conflict_type="business_transaction",
                                related_parties=transaction_parties,
                                description="Firm has transaction with party adverse to client",
                            )

        return None

    def screen_new_matter_intake(
        self,
        case_id: str,
        client_id: str,
        opposing_parties: list[str],
        assigned_attorney_id: str,
    ) -> tuple[bool, list[Conflict]]:
        """Screen a new matter for conflicts at intake.

        Returns (is_clear, conflicts_found).
        """
        conflicts_found: list[Conflict] = []

        # Check each opposing party
        for party in opposing_parties:
            # Direct adverse check
            direct = self.check_party_conflict(party, case_id)
            if direct:
                conflicts_found.append(direct)

            # Material limitation check
            limitation = self.check_material_limitation(assigned_attorney_id, party, case_id)
            if limitation:
                conflicts_found.append(limitation)

        # Business transaction check
        business = self.check_business_transaction_conflict(assigned_attorney_id, client_id, opposing_parties)
        if business:
            conflicts_found.append(business)

        # Add to index
        for party in opposing_parties:
            party_lower = party.lower()
            if party_lower not in self.parties_index:
                self.parties_index[party_lower] = set()
            self.parties_index[party_lower].add(case_id)

        is_clear = len(conflicts_found) == 0
        return is_clear, conflicts_found

    def check_lateral_hire(
        self,
        attorney_id: str,
        new_matters: list[dict],
    ) -> list[Conflict]:
        """Check lateral hire conflicts with prior firm matters.

        Detects conflicts when attorney joins firm with prior adverse matters.
        """
        conflicts_found: list[Conflict] = []

        if attorney_id not in self.prior_matters:
            return conflicts_found

        prior_matters = self.prior_matters[attorney_id]

        for new_matter in new_matters:
            for prior_matter in prior_matters:
                # Check if same party in adverse role
                similarity = self._fuzzy_match(
                    new_matter["party_name"].lower(),
                    prior_matter["party_name"].lower(),
                )

                if similarity > 0.85 and prior_matter.get("is_adverse"):
                    conflict = Conflict(
                        conflict_id=str(uuid4()),
                        party_name=new_matter["party_name"],
                        case_id=new_matter.get("case_id"),
                        conflict_type="lateral_hire",
                        related_parties=[prior_matter["party_name"]],
                        description="Lateral hire has prior adverse matter",
                    )
                    conflicts_found.append(conflict)

        return conflicts_found

    def get_waived_conflicts(self, case_id: str) -> list[Conflict]:
        """Get all waived conflicts for a case."""
        return [c for c in self.conflicts.values() if c.case_id == case_id and c.waived]

    def waive_conflict(
        self,
        conflict_id: str,
        informed_client: str,
        informed_opposing: str,
        waiver_details: dict,
    ) -> Conflict:
        """Record waiver of a detected conflict."""
        if conflict_id not in self.conflicts:
            raise ValueError(f"Conflict {conflict_id} not found")

        conflict = self.conflicts[conflict_id]
        conflict.waived = True
        conflict.waiver_details = {
            "informed_client": informed_client,
            "informed_opposing": informed_opposing,
            "waiver_date": datetime.now(),
            "details": waiver_details,
        }

        self.waivers[conflict_id] = conflict.waiver_details

        logger.info(f"Recorded waiver for conflict {conflict_id}")
        return conflict

    def add_prior_matter(
        self,
        attorney_id: str,
        party_name: str,
        case_name: str,
        is_adverse: bool,
        jurisdiction: str = "",
    ) -> None:
        """Add prior matter to attorney's history (from lateral hire)."""
        if attorney_id not in self.prior_matters:
            self.prior_matters[attorney_id] = []

        matter = {
            "party_name": party_name,
            "case_name": case_name,
            "is_adverse": is_adverse,
            "jurisdiction": jurisdiction,
            "added_at": datetime.now(),
        }

        self.prior_matters[attorney_id].append(matter)
        logger.info(f"Added prior matter for {attorney_id}")

    def generate_conflict_report(self) -> dict:
        """Generate summary report of all conflicts."""
        total_conflicts = len(self.conflicts)
        unwaived = sum(1 for c in self.conflicts.values() if not c.waived)
        waived = total_conflicts - unwaived

        by_type = {}
        for conflict in self.conflicts.values():
            ctype = conflict.conflict_type
            if ctype not in by_type:
                by_type[ctype] = 0
            by_type[ctype] += 1

        return {
            "total_conflicts": total_conflicts,
            "unwaived": unwaived,
            "waived": waived,
            "by_type": by_type,
            "conflicts": [
                {
                    "conflict_id": c.conflict_id,
                    "party": c.party_name,
                    "type": c.conflict_type,
                    "waived": c.waived,
                }
                for c in self.conflicts.values()
            ],
        }

    @staticmethod
    def _fuzzy_match(str1: str, str2: str) -> float:
        """Calculate string similarity using SequenceMatcher.

        Returns value 0-1 where 1 is perfect match.
        """
        norm1 = ConflictChecker._normalize_party_name(str1)
        norm2 = ConflictChecker._normalize_party_name(str2)

        seq_score = SequenceMatcher(None, norm1, norm2).ratio()

        tokens1 = set(norm1.split())
        tokens2 = set(norm2.split())
        if not tokens1 and not tokens2:
            return 1.0
        if not tokens1 or not tokens2:
            return 0.0

        overlap = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        jaccard = overlap / union if union else 0.0
        containment = overlap / min(len(tokens1), len(tokens2))

        return max(seq_score, jaccard, containment)

    @staticmethod
    def _normalize_party_name(name: str) -> str:
        """Normalize party names for robust conflict matching."""
        text = re.sub(r"[^a-z0-9\s]", " ", str(name or "").lower())
        tokens = [t for t in text.split() if t]
        expansions = {
            "corp": "corporation",
            "co": "company",
            "inc": "incorporated",
            "ltd": "limited",
        }
        normalized = [expansions.get(token, token) for token in tokens]
        return " ".join(normalized)

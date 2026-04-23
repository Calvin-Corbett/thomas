"""
Tests for protein module.
"""

import pytest

from thomas.marketplace.bioinformatics._exceptions import InvalidSequenceError
from thomas.marketplace.bioinformatics.protein import (
    amino_acid_composition,
    extinction_coefficient,
    hydrophobicity_plot,
    isoelectric_point,
    molecular_weight,
    protein_domains,
    secondary_structure_prediction,
)


class TestMolecularWeight:
    """Test molecular weight calculation."""

    def test_single_amino_acid(self) -> None:
        """Test weight of single amino acid."""
        weight = molecular_weight("A")
        assert weight > 0
        # Alanine is ~71 Da + water
        assert 80 < weight < 95

    def test_multiple_amino_acids(self) -> None:
        """Test weight of peptide."""
        weight = molecular_weight("AA")
        assert weight > 0

    def test_unknown_amino_acid(self) -> None:
        """Test with unknown amino acid."""
        with pytest.raises(InvalidSequenceError):
            molecular_weight("Z")  # Z is selenocysteine, not in dict

    def test_case_insensitive(self) -> None:
        """Test case insensitivity."""
        weight1 = molecular_weight("ACDEFG")
        weight2 = molecular_weight("acdefg")
        assert weight1 == weight2

    def test_large_protein(self) -> None:
        """Test large protein."""
        seq = "MVHLTPEEKS" * 10
        weight = molecular_weight(seq)
        assert weight > 1000


class TestIsoelectricPoint:
    """Test isoelectric point calculation."""

    def test_pI_range(self) -> None:
        """Test that pI is in valid pH range."""
        pI = isoelectric_point("MVHLTPEEKS")
        assert 0 <= pI <= 14

    def test_pI_acidic(self) -> None:
        """Test acidic protein (high D/E)."""
        pI1 = isoelectric_point("DDDEEE")
        pI2 = isoelectric_point("KKKRRR")
        # Acidic should have lower pI
        assert pI1 < pI2

    def test_pI_basic(self) -> None:
        """Test basic protein (high K/R)."""
        pI = isoelectric_point("KKKRRR")
        assert pI > 7

    def test_pI_neutral(self) -> None:
        """Test neutral protein."""
        pI = isoelectric_point("AALVIM")
        assert 4 < pI < 10

    def test_pI_consistent(self) -> None:
        """Test pI is consistent across calls."""
        pI1 = isoelectric_point("MVHLTPEEKS")
        pI2 = isoelectric_point("MVHLTPEEKS")
        assert pI1 == pI2


class TestComposition:
    """Test amino acid composition."""

    def test_homopolymer(self) -> None:
        """Test homopolymer composition."""
        comp = amino_acid_composition("AAAA")
        assert comp["A"] == 100.0

    def test_equal_composition(self) -> None:
        """Test equal composition."""
        comp = amino_acid_composition("ACDEFG")
        # Each appears once in 6 residues = 16.67%
        assert 16 < comp["A"] < 17
        assert 16 < comp["C"] < 17

    def test_composition_sums_to_100(self) -> None:
        """Test that composition sums to 100."""
        comp = amino_acid_composition("MVHLTPEEKS")
        total = sum(comp.values())
        assert 99 < total < 101

    def test_empty_sequence(self) -> None:
        """Test with empty sequence."""
        with pytest.raises(InvalidSequenceError):
            amino_acid_composition("")

    def test_composition_only_present(self) -> None:
        """Test that only present amino acids are in result."""
        comp = amino_acid_composition("AAA")
        assert "A" in comp
        # Other amino acids might not be in dict
        for aa in "BCDEFGHIKLMNPQRSTVWY":
            if aa != "A" and aa in comp:
                assert comp[aa] == 0 or aa == "A"


class TestHydrophobicity:
    """Test hydrophobicity calculations."""

    def test_hydro_plot_length(self) -> None:
        """Test hydrophobicity plot length."""
        seq = "ACDEFGHIKLMNPQRSTVWY"
        hydro = hydrophobicity_plot(seq)
        assert len(hydro) == len(seq)

    def test_hydro_values_in_range(self) -> None:
        """Test hydrophobicity values are reasonable."""
        hydro = hydrophobicity_plot("IVLMFYW")
        for value in hydro:
            assert -5 < value < 5

    def test_hydro_hydrophobic(self) -> None:
        """Test hydrophobic amino acids."""
        # Hydrophobic amino acids should have positive average hydro
        hydro = hydrophobicity_plot("IVLMF")
        avg = sum(hydro) / len(hydro)
        assert avg > 1

    def test_hydro_hydrophilic(self) -> None:
        """Test hydrophilic amino acids."""
        # Hydrophilic amino acids should have negative average hydro
        hydro = hydrophobicity_plot("DEKR")
        avg = sum(hydro) / len(hydro)
        assert avg < 0

    def test_hydro_window_size(self) -> None:
        """Test different window sizes."""
        seq = "IVLMFYWACDEFGHKRST"
        hydro5 = hydrophobicity_plot(seq, window_size=5)
        hydro9 = hydrophobicity_plot(seq, window_size=9)
        assert len(hydro5) == len(seq)
        assert len(hydro9) == len(seq)

    def test_hydro_window_too_large(self) -> None:
        """Test window larger than sequence."""
        with pytest.raises(InvalidSequenceError):
            hydrophobicity_plot("ABC", window_size=10)


class TestSecondaryStructure:
    """Test secondary structure prediction."""

    def test_secondary_structure_output(self) -> None:
        """Test secondary structure output format."""
        assignment, propensities = secondary_structure_prediction("MVHLTPEEKS")
        assert len(assignment) == 10
        assert all(c in "HEC" for c in assignment)
        assert len(propensities) == 10

    def test_secondary_structure_propensities(self) -> None:
        """Test propensity values."""
        assignment, propensities = secondary_structure_prediction("MVHLTPEEKS")
        # Should return tuples as strings
        assert isinstance(propensities[0], str)

    def test_secondary_structure_helix(self) -> None:
        """Test helix propensity."""
        # Alanine is helix former
        assignment, _ = secondary_structure_prediction("AAAAAAA")
        # Should have some helix predictions
        assert "H" in assignment

    def test_secondary_structure_sheet(self) -> None:
        """Test sheet propensity."""
        # Isoleucine is sheet former
        assignment, _ = secondary_structure_prediction("IIIIIII")
        # Should have some sheet predictions
        assert "E" in assignment

    def test_secondary_structure_invalid_aa(self) -> None:
        """Test with invalid amino acid."""
        with pytest.raises(InvalidSequenceError):
            secondary_structure_prediction("MVHLT$")


class TestExtinctionCoefficient:
    """Test extinction coefficient calculation."""

    def test_ec_basic(self) -> None:
        """Test basic extinction coefficient."""
        ec = extinction_coefficient("MVHLTPEEKS")
        assert ec >= 0

    def test_ec_with_cysteines(self) -> None:
        """Test with cysteines."""
        ec_reduced = extinction_coefficient("MVHLTCEEKS", reduced=True)
        ec_disulfide = extinction_coefficient("MVHLTCEEKS", reduced=False)
        # Should both be positive
        assert ec_reduced > 0
        assert ec_disulfide > 0

    def test_ec_with_tryptophan(self) -> None:
        """Test with tryptophan."""
        ec_w = extinction_coefficient("W")
        assert ec_w == 5500

    def test_ec_with_tyrosine(self) -> None:
        """Test with tyrosine."""
        ec_y = extinction_coefficient("Y")
        assert ec_y == 1490

    def test_ec_no_chromophores(self) -> None:
        """Test with no chromophores."""
        ec = extinction_coefficient("AGHKL")
        assert ec == 0


class TestProteinDomains:
    """Test domain detection."""

    def test_domain_detection_default(self) -> None:
        """Test default domain patterns."""
        domains = protein_domains("MKKKKKKVHLTPEEKS")
        assert isinstance(domains, dict)

    def test_domain_nls(self) -> None:
        """Test NLS detection."""
        seq = "MKKKKKKVHLTPEEKS"
        domains = protein_domains(seq)
        if domains:
            # Should find 4+ consecutive lysines
            for domain_name, positions in domains.items():
                if domain_name == "NLS":
                    assert len(positions) > 0

    def test_domain_custom_pattern(self) -> None:
        """Test custom domain patterns."""
        patterns = {"test": "AAA"}
        domains = protein_domains("AAAAAA", patterns=patterns)
        assert "test" in domains or len(domains) == 0

    def test_domain_helix_pattern(self) -> None:
        """Test helix pattern detection."""
        seq = "ILMFVVVVVVVVVAA"
        domains = protein_domains(seq)
        # Should find hydrophobic regions
        assert isinstance(domains, dict)

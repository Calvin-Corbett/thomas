"""
Thomas Bioinformatics Module

A comprehensive Python library for bioinformatics analysis including:
- Sequence manipulation and analysis (DNA, RNA, proteins)
- Sequence alignment (pairwise and multiple)
- BLAST-like homology searching
- Phylogenetic tree construction and analysis
- Motif discovery and analysis
- Protein characterization
- Population genetics calculations
- File format parsing (FASTA, FASTQ, GenBank, GFF3, PDB)
- Statistical analysis of sequences
"""

__version__ = "1.0.0"
__author__ = "Thomas"

from thomas.bioinformatics._exceptions import (
    AlignmentError,
    BioError,
    InvalidSequenceError,
)
from thomas.bioinformatics._types import (
    AlignmentResult,
    AminoAcid,
    BLASTHit,
    CodonTable,
    GeneFeature,
    PhyloTree,
    Sequence,
    SequenceStats,
    SubstitutionMatrix,
)
from thomas.bioinformatics.alignment import (
    multiple_sequence_alignment,
    needleman_wunsch,
    smith_waterman,
)
from thomas.bioinformatics.blast import (
    BLASTDatabase,
    blast_search,
    calculate_evalue,
)
from thomas.bioinformatics.io_formats import (
    parse_genbank,
    parse_gff3,
    parse_pdb,
    read_fasta,
    read_fastq,
    write_fasta_file,
    write_fastq_file,
)
from thomas.bioinformatics.motifs import (
    PositionWeightMatrix,
    find_motif_occurrences,
    find_restriction_sites,
)
from thomas.bioinformatics.phylogenetics import (
    bootstrap_support,
    distance_matrix,
    neighbor_joining,
    parse_newick,
    upgma_tree,
    write_newick,
)
from thomas.bioinformatics.population import (
    allele_frequency,
    calculate_fst,
    hardy_weinberg_test,
    heterozygosity,
    linkage_disequilibrium,
    nei_distance,
)
from thomas.bioinformatics.protein import (
    amino_acid_composition,
    extinction_coefficient,
    hydrophobicity_plot,
    isoelectric_point,
    molecular_weight,
    secondary_structure_prediction,
)
from thomas.bioinformatics.sequence import (
    complement,
    find_orfs,
    gc_content,
    nucleotide_frequency,
    parse_fasta,
    reverse_complement,
    transcribe,
    translate,
    validate_dna,
    validate_protein,
    validate_rna,
    write_fasta,
)
from thomas.bioinformatics.stats import (
    chi_squared_test,
    codon_usage_bias,
    gc_skew,
    kmer_frequency,
    sequence_complexity,
    sequence_entropy,
)

__all__ = [
    "Sequence",
    "AlignmentResult",
    "CodonTable",
    "AminoAcid",
    "PhyloTree",
    "BLASTHit",
    "GeneFeature",
    "SequenceStats",
    "SubstitutionMatrix",
    "BioError",
    "InvalidSequenceError",
    "AlignmentError",
    "validate_dna",
    "validate_rna",
    "validate_protein",
    "complement",
    "reverse_complement",
    "transcribe",
    "translate",
    "gc_content",
    "nucleotide_frequency",
    "find_orfs",
    "parse_fasta",
    "write_fasta",
    "needleman_wunsch",
    "smith_waterman",
    "multiple_sequence_alignment",
    "BLASTDatabase",
    "blast_search",
    "calculate_evalue",
    "distance_matrix",
    "upgma_tree",
    "neighbor_joining",
    "parse_newick",
    "write_newick",
    "bootstrap_support",
    "PositionWeightMatrix",
    "find_motif_occurrences",
    "find_restriction_sites",
    "molecular_weight",
    "isoelectric_point",
    "amino_acid_composition",
    "hydrophobicity_plot",
    "secondary_structure_prediction",
    "extinction_coefficient",
    "hardy_weinberg_test",
    "allele_frequency",
    "heterozygosity",
    "calculate_fst",
    "nei_distance",
    "linkage_disequilibrium",
    "read_fasta",
    "write_fasta_file",
    "read_fastq",
    "write_fastq_file",
    "parse_genbank",
    "parse_gff3",
    "parse_pdb",
    "sequence_entropy",
    "kmer_frequency",
    "sequence_complexity",
    "gc_skew",
    "codon_usage_bias",
    "chi_squared_test",
]

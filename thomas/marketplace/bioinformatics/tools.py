"""Tools for Bioinformatics module.

Provides tools for sequence analysis, alignment, BLAST search, and phylogenetics.
"""

from typing import Any

from thomas import bioinformatics
from thomas.tools.base import Tool, ToolResult


class SequenceAnalysisTool(Tool):
    """Analyze biological sequences."""

    name = "bioinformatics_sequence"
    category = "bioinformatics"
    description = "Analyze DNA, RNA, and protein sequences"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["gc_content", "validate", "translate", "find_orfs", "transcribe"],
                "description": "Sequence analysis action",
            },
            "sequence": {"type": "string", "description": "Biological sequence"},
            "seq_type": {"type": "string", "enum": ["dna", "rna", "protein"], "description": "Sequence type"},
        },
        "required": ["action", "sequence"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            sequence = args.get("sequence", "").upper()

            if not sequence:
                return ToolResult(ok=False, error="Sequence is required")

            if action == "gc_content":
                gc = bioinformatics.gc_content(sequence)
                return ToolResult(ok=True, data={"gc_content": gc, "sequence_length": len(sequence)})
            elif action == "validate":
                seq_type = args.get("seq_type", "dna")
                try:
                    if seq_type == "dna":
                        bioinformatics.validate_dna(sequence)
                    elif seq_type == "rna":
                        bioinformatics.validate_rna(sequence)
                    elif seq_type == "protein":
                        bioinformatics.validate_protein(sequence)
                    return ToolResult(ok=True, data={"valid": True, "type": seq_type})
                except bioinformatics.InvalidSequenceError as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "translate":
                try:
                    protein = bioinformatics.translate(sequence)
                    return ToolResult(ok=True, data={"protein": protein, "length": len(protein)})
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "find_orfs":
                orfs = bioinformatics.find_orfs(sequence)
                return ToolResult(
                    ok=True,
                    data={
                        "orfs_found": len(orfs),
                        "orfs": [{"start": orf[0], "end": orf[1], "length": orf[1] - orf[0]} for orf in orfs[:5]],
                    },
                )
            elif action == "transcribe":
                try:
                    rna = bioinformatics.transcribe(sequence)
                    return ToolResult(ok=True, data={"rna": rna, "length": len(rna)})
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class AlignmentTool(Tool):
    """Perform sequence alignments."""

    name = "bioinformatics_alignment"
    category = "bioinformatics"
    description = "Perform pairwise and multiple sequence alignments"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["needleman_wunsch", "smith_waterman", "msa"],
                "description": "Alignment algorithm",
            },
            "seq1": {"type": "string", "description": "First sequence"},
            "seq2": {"type": "string", "description": "Second sequence"},
            "sequences": {"type": "array", "items": {"type": "string"}, "description": "Multiple sequences for MSA"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "needleman_wunsch":
                seq1 = args.get("seq1", "")
                seq2 = args.get("seq2", "")
                if not seq1 or not seq2:
                    return ToolResult(ok=False, error="Both sequences required")

                try:
                    result = bioinformatics.needleman_wunsch(seq1, seq2)
                    return ToolResult(
                        ok=True,
                        data={
                            "alignment1": result.seq1_aligned[:50],
                            "alignment2": result.seq2_aligned[:50],
                            "score": result.score,
                            "identity": result.identity,
                        },
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "smith_waterman":
                seq1 = args.get("seq1", "")
                seq2 = args.get("seq2", "")
                if not seq1 or not seq2:
                    return ToolResult(ok=False, error="Both sequences required")

                try:
                    result = bioinformatics.smith_waterman(seq1, seq2)
                    return ToolResult(
                        ok=True,
                        data={
                            "alignment1": result.seq1_aligned[:50],
                            "alignment2": result.seq2_aligned[:50],
                            "score": result.score,
                        },
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "msa":
                sequences = args.get("sequences", [])
                if len(sequences) < 2:
                    return ToolResult(ok=False, error="At least 2 sequences required")

                try:
                    result = bioinformatics.multiple_sequence_alignment(sequences)
                    return ToolResult(
                        ok=True,
                        data={
                            "aligned_count": len(result.sequences),
                            "alignment_length": result.alignment_length,
                            "score": result.score,
                        },
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class BLASTTool(Tool):
    """Perform BLAST-like homology searches."""

    name = "bioinformatics_blast"
    category = "bioinformatics"
    description = "Search for homologous sequences in a database"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_db", "search", "calculate_evalue"],
                "description": "BLAST action",
            },
            "sequences": {"type": "array", "items": {"type": "string"}, "description": "Database sequences"},
            "query": {"type": "string", "description": "Query sequence"},
            "threshold": {"type": "number", "description": "E-value threshold"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_db":
                sequences = args.get("sequences", [])
                if not sequences:
                    return ToolResult(ok=False, error="Sequences required")

                try:
                    db = bioinformatics.BLASTDatabase(sequences)
                    return ToolResult(
                        ok=True,
                        data={
                            "db_size": len(sequences),
                            "total_residues": sum(len(s) for s in sequences),
                            "status": "created",
                        },
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "search":
                query = args.get("query", "")
                sequences = args.get("sequences", [])
                threshold = args.get("threshold", 0.001)

                if not query or not sequences:
                    return ToolResult(ok=False, error="Query and database required")

                try:
                    db = bioinformatics.BLASTDatabase(sequences)
                    hits = bioinformatics.blast_search(db, query, threshold)
                    return ToolResult(
                        ok=True, data={"hits_found": len(hits) if hits else 0, "threshold": threshold, "top_hits": 5}
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "calculate_evalue":
                alignment_length = args.get("alignment_length", 50)
                bit_score = args.get("bit_score", 50.0)

                try:
                    evalue = bioinformatics.calculate_evalue(bit_score, alignment_length)
                    return ToolResult(ok=True, data={"evalue": evalue, "bit_score": bit_score})
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PhylogeneticsTool(Tool):
    """Construct and analyze phylogenetic trees."""

    name = "bioinformatics_phylogenetics"
    category = "bioinformatics"
    description = "Build and analyze phylogenetic relationships"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["distance_matrix", "upgma", "neighbor_joining", "bootstrap"],
                "description": "Phylogenetics action",
            },
            "sequences": {"type": "array", "items": {"type": "string"}, "description": "Input sequences"},
            "newick": {"type": "string", "description": "Newick format tree"},
            "replicates": {"type": "integer", "description": "Bootstrap replicates"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "distance_matrix":
                sequences = args.get("sequences", [])
                if len(sequences) < 2:
                    return ToolResult(ok=False, error="At least 2 sequences required")

                try:
                    bioinformatics.distance_matrix(sequences)
                    return ToolResult(
                        ok=True,
                        data={"sequences": len(sequences), "distances_calculated": True, "matrix_size": len(sequences)},
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "upgma":
                sequences = args.get("sequences", [])
                if len(sequences) < 2:
                    return ToolResult(ok=False, error="At least 2 sequences required")

                try:
                    bioinformatics.upgma_tree(sequences)
                    return ToolResult(
                        ok=True, data={"tree_constructed": True, "method": "UPGMA", "sequences": len(sequences)}
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "neighbor_joining":
                sequences = args.get("sequences", [])
                if len(sequences) < 3:
                    return ToolResult(ok=False, error="At least 3 sequences required")

                try:
                    bioinformatics.neighbor_joining(sequences)
                    return ToolResult(
                        ok=True,
                        data={"tree_constructed": True, "method": "Neighbor-Joining", "sequences": len(sequences)},
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "bootstrap":
                sequences = args.get("sequences", [])
                replicates = args.get("replicates", 100)

                if len(sequences) < 2:
                    return ToolResult(ok=False, error="At least 2 sequences required")

                try:
                    bioinformatics.bootstrap_support(sequences, replicates)
                    return ToolResult(
                        ok=True, data={"bootstrap_replicates": replicates, "support_values_calculated": True}
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ProteinAnalysisTool(Tool):
    """Analyze protein properties."""

    name = "bioinformatics_protein"
    category = "bioinformatics"
    description = "Calculate protein properties and characteristics"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["molecular_weight", "isoelectric_point", "composition", "hydrophobicity"],
                "description": "Protein analysis action",
            },
            "sequence": {"type": "string", "description": "Protein sequence"},
        },
        "required": ["action", "sequence"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            sequence = args.get("sequence", "").upper()

            if not sequence:
                return ToolResult(ok=False, error="Sequence required")

            if action == "molecular_weight":
                try:
                    weight = bioinformatics.molecular_weight(sequence)
                    return ToolResult(ok=True, data={"molecular_weight": weight, "unit": "Da"})
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "isoelectric_point":
                try:
                    pI = bioinformatics.isoelectric_point(sequence)
                    return ToolResult(ok=True, data={"isoelectric_point": pI})
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "composition":
                try:
                    composition = bioinformatics.amino_acid_composition(sequence)
                    return ToolResult(ok=True, data={"composition": composition, "total_residues": len(sequence)})
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            elif action == "hydrophobicity":
                try:
                    bioinformatics.hydrophobicity_plot(sequence)
                    return ToolResult(
                        ok=True, data={"hydrophobicity_calculated": True, "sequence_length": len(sequence)}
                    )
                except Exception as e:
                    return ToolResult(ok=False, error=str(e))
            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_bioinformatics_tools(registry):
    """Register all bioinformatics tools."""
    registry.register(SequenceAnalysisTool())
    registry.register(AlignmentTool())
    registry.register(BLASTTool())
    registry.register(PhylogeneticsTool())
    registry.register(ProteinAnalysisTool())

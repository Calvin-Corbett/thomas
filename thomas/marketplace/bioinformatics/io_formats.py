"""
Bioinformatics file format parsing and writing.

Supports FASTA, FASTQ, GenBank, GFF3, and PDB formats with
automatic format detection and robust error handling.
"""

from dataclasses import dataclass

from thomas.marketplace.bioinformatics._types import GeneFeature, Sequence, SequenceType


@dataclass
class FastqRecord:
    """FASTQ sequence record."""

    header: str
    sequence: str
    quality: str
    description: str = ""

    def __post_init__(self) -> None:
        """Validate FASTQ record."""
        if len(self.sequence) != len(self.quality):
            raise ValueError("Sequence and quality must have equal length")


@dataclass
class GenBankRecord:
    """GenBank sequence record."""

    locus: str
    definition: str
    accession: str
    sequence: str
    features: list[GeneFeature]
    organism: str = ""


@dataclass
class GFF3Feature:
    """GFF3 format feature."""

    seqname: str
    source: str
    feature: str
    start: int
    end: int
    score: float | None
    strand: str
    frame: int
    attributes: dict[str, list[str]]


@dataclass
class PDBAtom:
    """PDB coordinate atom."""

    serial: int
    name: str
    residue_name: str
    chain: str
    residue_num: int
    x: float
    y: float
    z: float
    occupancy: float = 1.0
    temp_factor: float = 0.0
    element: str = ""


def read_fasta(filepath: str) -> list[Sequence]:
    """
    Read FASTA file and return Sequence objects.

    Args:
        filepath: Path to FASTA file

    Returns:
        List of Sequence objects

    Raises:
        FileNotFoundError: If file not found
        ValueError: If file format is invalid
    """
    sequences: list[Sequence] = []

    try:
        with open(filepath) as f:
            current_id: str | None = None
            current_desc: str = ""
            current_seq: list[str] = []

            for line in f:
                line = line.strip()

                if not line:
                    continue

                if line.startswith(">"):
                    # Save previous sequence
                    if current_id is not None:
                        seq_str = "".join(current_seq)
                        seq_type = _detect_type(seq_str)
                        sequences.append(
                            Sequence(id=current_id, seq=seq_str.upper(), seq_type=seq_type, description=current_desc)
                        )

                    # Parse header
                    header = line[1:]
                    parts = header.split(None, 1)
                    current_id = parts[0]
                    current_desc = parts[1] if len(parts) > 1 else ""
                    current_seq = []
                else:
                    current_seq.append(line)

            # Save last sequence
            if current_id is not None:
                seq_str = "".join(current_seq)
                seq_type = _detect_type(seq_str)
                sequences.append(
                    Sequence(id=current_id, seq=seq_str.upper(), seq_type=seq_type, description=current_desc)
                )

    except FileNotFoundError:
        raise FileNotFoundError(f"FASTA file not found: {filepath}")

    return sequences


def write_fasta_file(sequences: list[Sequence], filepath: str, line_width: int = 70) -> None:
    """
    Write sequences to FASTA file.

    Args:
        sequences: List of Sequence objects
        filepath: Output file path
        line_width: Characters per line
    """
    with open(filepath, "w") as f:
        for seq in sequences:
            # Write header
            header = f">{seq.id}"
            if seq.description:
                header += f" {seq.description}"
            f.write(header + "\n")

            # Write sequence with line wrapping
            for i in range(0, len(seq.seq), line_width):
                f.write(seq.seq[i : i + line_width] + "\n")


def read_fastq(filepath: str) -> list[FastqRecord]:
    """
    Read FASTQ file.

    Args:
        filepath: Path to FASTQ file

    Returns:
        List of FastqRecord objects

    Raises:
        FileNotFoundError: If file not found
        ValueError: If file format is invalid
    """
    records: list[FastqRecord] = []

    try:
        with open(filepath) as f:
            lines = f.readlines()

            if len(lines) % 4 != 0:
                raise ValueError("FASTQ file must have 4 lines per record")

            for i in range(0, len(lines), 4):
                header_line = lines[i].strip()
                seq_line = lines[i + 1].strip()
                sep_line = lines[i + 2].strip()
                qual_line = lines[i + 3].strip()

                if not header_line.startswith("@"):
                    raise ValueError(f"Invalid FASTQ header at line {i + 1}")

                if not sep_line.startswith("+"):
                    raise ValueError(f"Invalid FASTQ separator at line {i + 3}")

                if len(seq_line) != len(qual_line):
                    raise ValueError(f"Sequence/quality length mismatch at record {i // 4 + 1}")

                header = header_line[1:]
                parts = header.split(None, 1)
                seq_id = parts[0]
                description = parts[1] if len(parts) > 1 else ""

                records.append(
                    FastqRecord(header=seq_id, sequence=seq_line, quality=qual_line, description=description)
                )

    except FileNotFoundError:
        raise FileNotFoundError(f"FASTQ file not found: {filepath}")

    return records


def write_fastq_file(records: list[FastqRecord], filepath: str) -> None:
    """
    Write records to FASTQ file.

    Args:
        records: List of FastqRecord objects
        filepath: Output file path
    """
    with open(filepath, "w") as f:
        for record in records:
            f.write(f"@{record.header}")
            if record.description:
                f.write(f" {record.description}")
            f.write("\n")
            f.write(f"{record.sequence}\n")
            f.write(f"+{record.header}\n")
            f.write(f"{record.quality}\n")


def parse_genbank(filepath: str) -> list[GenBankRecord]:
    """
    Parse GenBank format file.

    Args:
        filepath: Path to GenBank file

    Returns:
        List of GenBankRecord objects

    Raises:
        FileNotFoundError: If file not found
    """
    records: list[GenBankRecord] = []

    try:
        with open(filepath) as f:
            content = f.read()

    except FileNotFoundError:
        raise FileNotFoundError(f"GenBank file not found: {filepath}")

    # Parse records separated by //
    record_strs = content.split("//")

    for record_str in record_strs:
        if not record_str.strip():
            continue

        lines = record_str.strip().split("\n")

        locus = ""
        definition = ""
        accession = ""
        organism = ""
        sequence = ""
        features: list[GeneFeature] = []
        in_sequence = False

        for line in lines:
            if line.startswith("LOCUS"):
                locus = line[12:].split()[0]
            elif line.startswith("DEFINITION"):
                definition = line[12:].strip()
            elif line.startswith("ACCESSION"):
                accession = line[12:].split()[0]
            elif line.startswith("ORGANISM"):
                organism = line[12:].strip()
            elif line.startswith("FEATURES"):
                in_sequence = False
            elif line.startswith("ORIGIN"):
                in_sequence = True
            elif in_sequence:
                # Extract sequence
                parts = line.split()
                for part in parts[1:]:
                    sequence += part

        if locus:
            records.append(
                GenBankRecord(
                    locus=locus,
                    definition=definition,
                    accession=accession,
                    sequence=sequence.upper(),
                    features=features,
                    organism=organism,
                )
            )

    return records


def parse_gff3(filepath: str) -> list[GFF3Feature]:
    """
    Parse GFF3 format file.

    Args:
        filepath: Path to GFF3 file

    Returns:
        List of GFF3Feature objects

    Raises:
        FileNotFoundError: If file not found
    """
    features: list[GFF3Feature] = []

    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()

                if not line or line.startswith("#"):
                    continue

                parts = line.split("\t")

                if len(parts) < 8:
                    continue

                seqname = parts[0]
                source = parts[1]
                feature = parts[2]
                start = int(parts[3]) - 1  # Convert to 0-based
                end = int(parts[4])
                score = float(parts[5]) if parts[5] != "." else None
                strand = parts[6]
                frame = int(parts[7])

                # Parse attributes
                attr_str = parts[8] if len(parts) > 8 else ""
                attributes: dict[str, list[str]] = {}

                for attr in attr_str.split(";"):
                    if "=" in attr:
                        key, val = attr.split("=", 1)
                        attributes[key] = val.split(",")

                features.append(
                    GFF3Feature(
                        seqname=seqname,
                        source=source,
                        feature=feature,
                        start=start,
                        end=end,
                        score=score,
                        strand=strand,
                        frame=frame,
                        attributes=attributes,
                    )
                )

    except FileNotFoundError:
        raise FileNotFoundError(f"GFF3 file not found: {filepath}")

    return features


def parse_pdb(filepath: str) -> list[PDBAtom]:
    """
    Parse PDB coordinate file.

    Args:
        filepath: Path to PDB file

    Returns:
        List of PDBAtom objects

    Raises:
        FileNotFoundError: If file not found
    """
    atoms: list[PDBAtom] = []

    try:
        with open(filepath) as f:
            for line in f:
                if line.startswith("ATOM") or line.startswith("HETATM"):
                    serial = int(line[6:11])
                    name = line[12:16].strip()
                    residue_name = line[17:20].strip()
                    chain = line[21].strip()
                    residue_num = int(line[22:26])

                    x = float(line[30:38])
                    y = float(line[38:46])
                    z = float(line[46:54])

                    occupancy = float(line[54:60]) if len(line) > 60 else 1.0
                    temp_factor = float(line[60:66]) if len(line) > 66 else 0.0
                    element = line[76:78].strip() if len(line) > 78 else ""

                    atoms.append(
                        PDBAtom(
                            serial=serial,
                            name=name,
                            residue_name=residue_name,
                            chain=chain,
                            residue_num=residue_num,
                            x=x,
                            y=y,
                            z=z,
                            occupancy=occupancy,
                            temp_factor=temp_factor,
                            element=element,
                        )
                    )

    except FileNotFoundError:
        raise FileNotFoundError(f"PDB file not found: {filepath}")

    return atoms


def _detect_type(seq: str) -> SequenceType:
    """Detect sequence type from composition."""
    seq = seq.upper()

    has_u = "U" in seq
    has_t = "T" in seq

    if has_u and not has_t:
        return SequenceType.RNA
    elif has_t and not has_u:
        return SequenceType.DNA
    else:
        # Check if protein
        protein_chars = set("EFIPQZ")
        if any(c in seq for c in protein_chars):
            return SequenceType.PROTEIN

        return SequenceType.DNA


def auto_detect_format(filepath: str) -> str:
    """
    Auto-detect file format by reading first line.

    Args:
        filepath: Path to file

    Returns:
        Format name ('fasta', 'fastq', 'genbank', 'gff3', 'pdb')
    """
    try:
        with open(filepath) as f:
            first_line = f.readline().strip()

            if first_line.startswith(">"):
                # Could be FASTA or FASTQ, check further
                f.readline().strip()
                third_line = f.readline().strip()

                if third_line.startswith("+"):
                    return "fastq"
                else:
                    return "fasta"

            elif first_line.startswith("@"):
                return "fastq"

            elif first_line.startswith("LOCUS"):
                return "genbank"

            elif first_line.startswith("#") and "gff" in first_line.lower():
                return "gff3"

            elif first_line.startswith("HEADER") or first_line.startswith("ATOM"):
                return "pdb"

            elif "\t" in first_line:
                return "gff3"

    except FileNotFoundError:
        raise FileNotFoundError(f"File not found: {filepath}")

    return "fasta"

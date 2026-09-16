using System.Text.Json.Serialization;

namespace CadEngine;

/// <summary>
/// Shape of the <c>cad_geometry.json</c> file consumed by the Python pipeline.
/// Every numeric field is exact drawing data — no rounding beyond 6 decimals,
/// no derived/semantic fields.
/// </summary>
public sealed class CadExport
{
    [JsonPropertyName("source_file")]
    public string SourceFile { get; init; } = string.Empty;

    [JsonPropertyName("extracted_at")]
    public string ExtractedAt { get; init; } = string.Empty;

    [JsonPropertyName("metadata")]
    public CadMetadata Metadata { get; set; } = new();

    /// <summary>Line / LwPolyline / Insert entities with exact coordinates.</summary>
    [JsonPropertyName("entities")]
    public List<GeometryEntityDto> Entities { get; init; } = new();

    /// <summary>TEXT / MTEXT entities — semantic hints only, never measured.</summary>
    [JsonPropertyName("texts")]
    public List<TextDto> Texts { get; init; } = new();

    /// <summary>Named block definitions (summary) for semantic context.</summary>
    [JsonPropertyName("blocks")]
    public List<BlockSummaryDto> Blocks { get; init; } = new();

    [JsonPropertyName("layers")]
    public List<string> Layers { get; init; } = new();
}

public sealed class CadMetadata
{
    [JsonPropertyName("dwg_version")]
    public string DwgVersion { get; set; } = "unknown";

    /// <summary>INSUNITS header variable (e.g. "Millimeters", "Meters").</summary>
    [JsonPropertyName("units")]
    public string Units { get; set; } = "Unknown";

    [JsonPropertyName("entity_count")]
    public int EntityCount { get; set; }
}

public sealed class GeometryEntityDto
{
    /// <summary>Stable DWG object handle (hex) — the id referenced by the AI mapping.</summary>
    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    /// <summary>"Line" | "LwPolyline" | "Insert".</summary>
    [JsonPropertyName("type")]
    public string Type { get; init; } = string.Empty;

    [JsonPropertyName("layer")]
    public string Layer { get; init; } = "0";

    // --- Line -------------------------------------------------------------
    [JsonPropertyName("start")]
    public double[]? Start { get; set; }

    [JsonPropertyName("end")]
    public double[]? End { get; set; }

    // --- LwPolyline --------------------------------------------------------
    [JsonPropertyName("vertices")]
    public List<double[]>? Vertices { get; set; }

    [JsonPropertyName("closed")]
    public bool? Closed { get; set; }

    // --- Shared -------------------------------------------------------------
    /// <summary>Chord length in drawing units (arc segments approximated).</summary>
    [JsonPropertyName("length")]
    public double? Length { get; set; }

    // --- Insert (block reference) -------------------------------------------
    [JsonPropertyName("block_name")]
    public string? BlockName { get; set; }

    [JsonPropertyName("position")]
    public double[]? Position { get; set; }

    [JsonPropertyName("attributes")]
    public List<BlockAttributeDto>? Attributes { get; set; }
}

public sealed class BlockAttributeDto
{
    [JsonPropertyName("tag")]
    public string Tag { get; init; } = string.Empty;

    [JsonPropertyName("value")]
    public string Value { get; init; } = string.Empty;
}

public sealed class TextDto
{
    [JsonPropertyName("id")]
    public string Id { get; init; } = string.Empty;

    /// <summary>"TEXT" or "MTEXT" (ObjectName from ACadSharp).</summary>
    [JsonPropertyName("type")]
    public string Type { get; init; } = "TEXT";

    [JsonPropertyName("layer")]
    public string Layer { get; init; } = "0";

    [JsonPropertyName("value")]
    public string Value { get; init; } = string.Empty;

    [JsonPropertyName("position")]
    public double[]? Position { get; init; }
}

public sealed class BlockSummaryDto
{
    [JsonPropertyName("name")]
    public string Name { get; init; } = string.Empty;

    /// <summary>Count of contained entities per .NET type name.</summary>
    [JsonPropertyName("entity_types")]
    public Dictionary<string, int> EntityTypes { get; init; } = new();

    /// <summary>Attribute definition tags declared by this block.</summary>
    [JsonPropertyName("attribute_tags")]
    public List<string> AttributeTags { get; init; } = new();
}

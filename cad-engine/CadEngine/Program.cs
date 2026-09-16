using System.Text.Json;
using System.Text.Json.Serialization;
using ACadSharp;
using ACadSharp.IO;
using CadEngine;
using CadEngine.Extraction;

// ---------------------------------------------------------------------------
// Hybrid CAD Compliance System — Phase 1: Deterministic Extraction
//
// Usage:
//   cad-engine <input.dwg|input.dxf> <output.json>
//
// Loads a DWG file with ACadSharp and serializes exact geometric data
// (coordinates, layer names, block attributes) into a minified JSON file
// consumed by the Python orchestration backend.
//
// This tool performs NO interpretation of the drawing: deciding what a line
// *means* is the AI's job (Phase 2) and measuring distances is the Python
// engine's job (Phase 3). Determinism ends where this binary ends.
// ---------------------------------------------------------------------------

if (args.Length < 2)
{
    Console.Error.WriteLine("Usage: cad-engine <input.dwg|input.dxf> <output.json>");
    return 64;
}

string inputPath = args[0];
string outputPath = args[1];

if (!File.Exists(inputPath))
{
    Console.Error.WriteLine($"[cad-engine] ERROR: input file not found: {inputPath}");
    return 66;
}

try
{
    using FileStream stream = File.OpenRead(inputPath);

    // Spec: CadDocument doc = DwgReader.Read(stream);
    CadDocument doc = Path.GetExtension(inputPath).Equals(".dxf", StringComparison.OrdinalIgnoreCase)
        ? DxfReader.Read(stream, new DxfReaderConfiguration())
        : DwgReader.Read(stream, new DwgReaderConfiguration());

    CadExport export = GeometryExtractor.Extract(doc, Path.GetFileName(inputPath));

    var jsonOptions = new JsonSerializerOptions
    {
        WriteIndented = false, // minified cad_geometry.json
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    File.WriteAllText(outputPath, JsonSerializer.Serialize(export, jsonOptions));

    Console.WriteLine(
        $"[cad-engine] OK: {export.Entities.Count} geometry entities, " +
        $"{export.Texts.Count} texts, {export.Blocks.Count} blocks -> {outputPath}");
    return 0;
}
catch (Exception exception)
{
    Console.Error.WriteLine($"[cad-engine] ERROR: {exception.Message}");
    return 1;
}

using ACadSharp;
using ACadSharp.Entities;
using ACadSharp.Tables;

namespace CadEngine.Extraction;

/// <summary>
/// Phase 1 of the hybrid compliance pipeline: deterministic extraction.
/// Walks the model space of a <see cref="CadDocument"/> and converts every
/// Line / LwPolyline / Insert into plain numeric DTOs, plus text and block
/// summaries used as semantic hints. No heuristics, no semantics, no AI.
/// </summary>
public static class GeometryExtractor
{
    private const int Precision = 6;

    public static CadExport Extract(CadDocument doc, string sourceFile)
    {
        var export = new CadExport
        {
            SourceFile = sourceFile,
            ExtractedAt = DateTime.UtcNow.ToString("O"),
        };

        foreach (Entity entity in doc.Entities)
        {
            switch (entity)
            {
                case Line line:
                    export.Entities.Add(MapLine(line));
                    break;
                case LwPolyline polyline:
                    export.Entities.Add(MapLwPolyline(polyline));
                    break;
                case Insert insert:
                    export.Entities.Add(MapInsert(insert));
                    break;
                case TextEntity text: // covers TEXT and MTEXT — semantic hints only
                    export.Texts.Add(MapText(text));
                    break;
                default:
                    // Arcs, circles, hatches, etc. are not part of setback verification.
                    break;
            }
        }

        if (doc.Blocks is not null)
        {
            foreach (BlockRecord block in doc.Blocks)
            {
                // Skip *Model_Space, *Paper_Space and anonymous (*U...) blocks.
                if (string.IsNullOrEmpty(block.Name) || block.Name.StartsWith("*"))
                {
                    continue;
                }

                export.Blocks.Add(MapBlock(block));
            }
        }

        if (doc.Layers is not null)
        {
            foreach (Layer layer in doc.Layers)
            {
                if (!string.IsNullOrEmpty(layer.Name))
                {
                    export.Layers.Add(layer.Name);
                }
            }
        }

        export.Metadata = new CadMetadata
        {
            DwgVersion = GetDocumentVersion(doc),
            Units = GetDrawingUnits(doc),
            EntityCount = doc.Entities.Count,
        };

        return export;
    }

    // --- Entity mapping ------------------------------------------------------

    private static GeometryEntityDto MapLine(Line line)
    {
        return new GeometryEntityDto
        {
            Id = HandleId(line),
            Type = "Line",
            Layer = LayerName(line),
            Start = Point(line.StartPoint.X, line.StartPoint.Y),
            End = Point(line.EndPoint.X, line.EndPoint.Y),
            Length = Round(Distance(
                line.StartPoint.X, line.StartPoint.Y,
                line.EndPoint.X, line.EndPoint.Y)),
        };
    }

    private static GeometryEntityDto MapLwPolyline(LwPolyline polyline)
    {
        var vertices = new List<double[]>();
        double length = 0;
        double previousX = 0;
        double previousY = 0;
        bool hasPrevious = false;

        if (polyline.Vertices is not null)
        {
            foreach (LwPolyline.Vertex vertex in polyline.Vertices)
            {
                double x = vertex.Location.X;
                double y = vertex.Location.Y;
                vertices.Add(Point(x, y));

                if (hasPrevious)
                {
                    length += Distance(previousX, previousY, x, y);
                }

                previousX = x;
                previousY = y;
                hasPrevious = true;
            }
        }

        if (polyline.IsClosed && vertices.Count > 2)
        {
            double[] first = vertices[0];
            double[] last = vertices[vertices.Count - 1];
            length += Distance(last[0], last[1], first[0], first[1]);
        }

        return new GeometryEntityDto
        {
            Id = HandleId(polyline),
            Type = "LwPolyline",
            Layer = LayerName(polyline),
            Vertices = vertices,
            Closed = polyline.IsClosed,
            Length = Round(length),
        };
    }

    private static GeometryEntityDto MapInsert(Insert insert)
    {
        var dto = new GeometryEntityDto
        {
            Id = HandleId(insert),
            Type = "Insert",
            Layer = LayerName(insert),
            BlockName = insert.Block?.Name,
            Position = Point(insert.InsertPoint.X, insert.InsertPoint.Y),
        };

        if (insert.HasAttributes)
        {
            var attributes = new List<BlockAttributeDto>();
            foreach (AttributeEntity attribute in insert.Attributes)
            {
                attributes.Add(new BlockAttributeDto
                {
                    Tag = attribute.Tag ?? string.Empty,
                    Value = attribute.Value ?? string.Empty,
                });
            }

            dto.Attributes = attributes;
        }

        return dto;
    }

    private static TextDto MapText(TextEntity text)
    {
        return new TextDto
        {
            Id = HandleId(text),
            Type = text.ObjectName, // "TEXT" or "MTEXT"
            Layer = LayerName(text),
            Value = StripFormatting(text.Value ?? string.Empty),
            Position = Point(text.InsertPoint.X, text.InsertPoint.Y),
        };
    }

    private static BlockSummaryDto MapBlock(BlockRecord block)
    {
        var summary = new BlockSummaryDto { Name = block.Name ?? string.Empty };

        if (block.Entities is not null)
        {
            foreach (Entity entity in block.Entities)
            {
                string typeName = entity.GetType().Name;
                summary.EntityTypes[typeName] =
                    summary.EntityTypes.TryGetValue(typeName, out int count) ? count + 1 : 1;

                if (entity is AttributeDefinition definition && !string.IsNullOrEmpty(definition.Tag))
                {
                    summary.AttributeTags.Add(definition.Tag);
                }
            }
        }

        return summary;
    }

    // --- Helpers ----------------------------------------------------------------

    private static string HandleId(CadObject cadObject) => cadObject.Handle.ToString("X");

    private static string LayerName(Entity entity) => entity.Layer?.Name ?? "0";

    private static double[] Point(double x, double y) => new[] { Round(x), Round(y) };

    private static double Distance(double x1, double y1, double x2, double y2) =>
        Math.Sqrt((x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1));

    private static double Round(double value) => Math.Round(value, Precision);

    /// <summary>Removes common AutoCAD inline formatting codes from text values.</summary>
    private static string StripFormatting(string value) =>
        System.Text.RegularExpressions.Regex.Replace(value, @"\\\\[A-Za-z][^;]*;", string.Empty).Trim();

    private static string GetDrawingUnits(CadDocument doc)
    {
        try
        {
            return doc.Header.Insunits.ToString();
        }
        catch
        {
            return "Unknown";
        }
    }

    /// <summary>Reads CadDocument.ApplicationVersion defensively (reflection).</summary>
    private static string GetDocumentVersion(CadDocument doc)
    {
        try
        {
            var property = doc.GetType().GetProperty("ApplicationVersion");
            return property?.GetValue(doc)?.ToString() ?? "unknown";
        }
        catch
        {
            return "unknown";
        }
    }
}

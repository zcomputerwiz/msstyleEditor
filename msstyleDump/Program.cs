using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using libmsstyle;

namespace msstyleDump
{
    class Program
    {
        static int Main(string[] args)
        {
            string inputPath = null;
            string outputPath = null;

            for (int i = 0; i < args.Length; i++)
            {
                string arg = args[i];
                if (arg == "--dump" || arg == "-d")
                {
                    if (i + 1 < args.Length)
                    {
                        inputPath = args[++i];
                    }
                }
                else if (arg == "-o" || arg == "--out" || arg == "--output")
                {
                    if (i + 1 < args.Length)
                    {
                        outputPath = args[++i];
                    }
                }
                else if (arg == "-h" || arg == "--help")
                {
                    PrintUsage();
                    return 0;
                }
                else if (!arg.StartsWith("-") && inputPath == null)
                {
                    inputPath = arg;
                }
            }

            if (string.IsNullOrEmpty(inputPath))
            {
                PrintUsage();
                return 1;
            }

            if (!File.Exists(inputPath))
            {
                Console.Error.WriteLine("Error: File not found: " + inputPath);
                return 1;
            }

            try
            {
                using (var style = new VisualStyle())
                {
                    style.Load(inputPath);
                    string json = DumpToJson(style, inputPath);

                    if (!string.IsNullOrEmpty(outputPath))
                    {
                        string dir = Path.GetDirectoryName(Path.GetFullPath(outputPath));
                        if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                        {
                            Directory.CreateDirectory(dir);
                        }
                        File.WriteAllText(outputPath, json, Encoding.UTF8);
                        Console.WriteLine("Dumped {0} properties from '{1}' to '{2}'", style.NumProperties, Path.GetFileName(inputPath), outputPath);
                    }
                    else
                    {
                        Console.WriteLine(json);
                    }
                }
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("Error dumping style: " + ex.Message);
                Console.Error.WriteLine(ex.StackTrace);
                return 2;
            }
        }

        static void PrintUsage()
        {
            Console.WriteLine("msstyleDump - Dump .msstyles visual style contents to JSON");
            Console.WriteLine("Usage: msstyleDump [--dump] <file.msstyles> [-o <output.json>]");
            Console.WriteLine();
            Console.WriteLine("Options:");
            Console.WriteLine("  --dump, -d <file>    Path to .msstyles file to parse");
            Console.WriteLine("  -o, --out <file>     Write JSON output to file (default: stdout)");
            Console.WriteLine("  -h, --help           Display this help message");
        }

        static string DumpToJson(VisualStyle style, string filePath)
        {
            var jw = new JsonWriter();
            jw.BeginObject();

            jw.WriteProperty("formatVersion", 4);
            jw.WriteProperty("file", Path.GetFileName(filePath));
            jw.WriteProperty("fullPath", Path.GetFullPath(filePath));
            jw.WriteProperty("platform", style.Platform.ToString());
            jw.WriteProperty("numProperties", style.NumProperties);

            // Resource lists
            List<int> imageIds = style.GetResourceIds("IMAGE");
            jw.WritePropertyName("imageResources");
            jw.BeginArray();
            foreach (var id in imageIds)
            {
                jw.WriteValue(id);
            }
            jw.EndArray();

            List<int> streamIds = style.GetResourceIds("STREAM");
            jw.WritePropertyName("streamResources");
            jw.BeginArray();
            foreach (var id in streamIds)
            {
                jw.WriteValue(id);
            }
            jw.EndArray();

            // String tables
            jw.WritePropertyName("stringTables");
            jw.BeginObject();
            foreach (var kvp in style.StringTables)
            {
                jw.WritePropertyName(kvp.Key.ToString());
                jw.BeginObject();
                foreach (var strEntry in kvp.Value.OrderBy(s => s.Key))
                {
                    jw.WriteProperty(strEntry.Key.ToString(), strEntry.Value);
                }
                jw.EndObject();
            }
            jw.EndObject();

            // Atlas entries summary
            jw.WritePropertyName("atlasEntries");
            jw.BeginArray();
            foreach (var cls in style.Classes.Values.OrderBy(c => c.ClassId))
            {
                foreach (var part in cls.Parts.Values.OrderBy(p => p.PartId))
                {
                    foreach (var state in part.States.Values.OrderBy(s => s.StateId))
                    {
                        var atlasRectProp = state.Properties.FirstOrDefault(p => p.Header.nameID == (int)IDENTIFIER.ATLASRECT);
                        if (atlasRectProp != null)
                        {
                            var atlasImgProp = state.Properties.FirstOrDefault(p => p.Header.nameID == (int)IDENTIFIER.ATLASIMAGE);
                            var atlasInputProp = state.Properties.FirstOrDefault(p => p.Header.nameID == (int)IDENTIFIER.ATLASINPUTIMAGE);

                            jw.BeginObject();
                            jw.WriteProperty("classId", cls.ClassId);
                            jw.WriteProperty("className", cls.ClassName);
                            jw.WriteProperty("partId", part.PartId);
                            jw.WriteProperty("partName", part.PartName);
                            jw.WriteProperty("stateId", state.StateId);
                            jw.WriteProperty("stateName", state.StateName);

                            Margins m = atlasRectProp.GetValue() as Margins;
                            if (m != null)
                            {
                                jw.WritePropertyName("rect");
                                jw.BeginObject();
                                jw.WriteProperty("left", m.Left);
                                jw.WriteProperty("top", m.Top);
                                jw.WriteProperty("right", m.Right);
                                jw.WriteProperty("bottom", m.Bottom);
                                jw.EndObject();
                            }

                            if (atlasImgProp != null)
                            {
                                jw.WriteProperty("atlasImageResourceId", atlasImgProp.Header.shortFlag);
                            }
                            if (atlasInputProp != null)
                            {
                                jw.WriteProperty("atlasInputImage", atlasInputProp.GetValue() as string ?? "");
                            }
                            jw.EndObject();
                        }
                    }
                }
            }
            jw.EndArray();

            // Classes, parts, states, properties
            jw.WritePropertyName("classes");
            jw.BeginArray();
            foreach (var cls in style.Classes.Values.OrderBy(c => c.ClassId))
            {
                jw.BeginObject();
                jw.WriteProperty("classId", cls.ClassId);
                jw.WriteProperty("className", cls.ClassName);

                jw.WritePropertyName("parts");
                jw.BeginArray();
                foreach (var part in cls.Parts.Values.OrderBy(p => p.PartId))
                {
                    jw.BeginObject();
                    jw.WriteProperty("partId", part.PartId);
                    jw.WriteProperty("partName", part.PartName);

                    jw.WritePropertyName("states");
                    jw.BeginArray();
                    foreach (var state in part.States.Values.OrderBy(s => s.StateId))
                    {
                        jw.BeginObject();
                        jw.WriteProperty("stateId", state.StateId);
                        jw.WriteProperty("stateName", state.StateName);

                        jw.WritePropertyName("properties");
                        jw.BeginArray();
                        foreach (var prop in state.Properties.OrderBy(p => p.Header.nameID))
                        {
                            WritePropertyObject(jw, prop);
                        }
                        jw.EndArray();

                        jw.EndObject();
                    }
                    jw.EndArray();

                    jw.EndObject();
                }
                jw.EndArray();

                jw.EndObject();
            }
            jw.EndArray();

            // Timing functions
            if (style.TimingFunctions != null && style.TimingFunctions.Count > 0)
            {
                jw.WritePropertyName("timingFunctions");
                jw.BeginArray();
                foreach (var tf in style.TimingFunctions)
                {
                    jw.BeginObject();
                    jw.WriteProperty("type", tf.Type.ToString());
                    if (tf.CubicBezier != null)
                    {
                        jw.WritePropertyName("cubicBezier");
                        jw.BeginObject();
                        jw.WriteProperty("rx0", tf.CubicBezier.RX0);
                        jw.WriteProperty("ry0", tf.CubicBezier.RY0);
                        jw.WriteProperty("rx1", tf.CubicBezier.RX1);
                        jw.WriteProperty("ry1", tf.CubicBezier.RY1);
                        jw.EndObject();
                    }
                    jw.EndObject();
                }
                jw.EndArray();
            }

            // Animations
            if (style.Animations != null && style.Animations.Count > 0)
            {
                jw.WritePropertyName("animations");
                jw.BeginArray();
                foreach (var anim in style.Animations)
                {
                    jw.BeginObject();
                    jw.WriteProperty("animationFlags", (int)anim.AnimationFlags);
                    jw.WriteProperty("transformCount", anim.TransformCount);
                    jw.WriteProperty("staggerDelay", anim.StaggerDelay);
                    jw.WriteProperty("staggerDelayCap", anim.StaggerDelayCap);
                    jw.WriteProperty("staggerDelayFactor", anim.StaggerDelayFactor);
                    jw.WriteProperty("zOrder", anim.ZOrder);
                    jw.WriteProperty("backgroundPartId", anim.BackgroundPartID);
                    jw.WriteProperty("tuningLevel", anim.TuningLevel);
                    jw.WriteProperty("perspective", anim.Perspective);
                    jw.EndObject();
                }
                jw.EndArray();
            }

            jw.EndObject();
            return jw.ToString();
        }

        static void WritePropertyObject(JsonWriter jw, StyleProperty prop)
        {
            jw.BeginObject();
            jw.WriteProperty("nameId", prop.Header.nameID);

            PropertyInfo propInfo;
            string propName = VisualStyleProperties.PROPERTY_INFO_MAP.TryGetValue(prop.Header.nameID, out propInfo) ? propInfo.Name : "UNKNOWN_" + prop.Header.nameID;
            jw.WriteProperty("name", propName);

            jw.WriteProperty("typeId", prop.Header.typeID);
            string typeName = Enum.IsDefined(typeof(IDENTIFIER), prop.Header.typeID) ?
                ((IDENTIFIER)prop.Header.typeID).ToString() : "TYPE_" + prop.Header.typeID;
            jw.WriteProperty("typeName", typeName);

            jw.WriteProperty("shortFlag", prop.Header.shortFlag);
            jw.WriteProperty("sizeInBytes", prop.Header.sizeInBytes);

            jw.WritePropertyName("value");
            WriteTypedValue(jw, prop);

            jw.EndObject();
        }

        static void WriteTypedValue(JsonWriter jw, StyleProperty prop)
        {
            IDENTIFIER type = (IDENTIFIER)prop.Header.typeID;
            switch (type)
            {
                case IDENTIFIER.INT:
                case IDENTIFIER.SIZE:
                    {
                        int v = prop.GetValue() is int iv ? iv : 0;
                        jw.WriteValue(v);
                        break;
                    }
                case IDENTIFIER.BOOLTYPE:
                    {
                        bool b = prop.GetValue() is bool bv && bv;
                        jw.WriteValue(b);
                        break;
                    }
                case IDENTIFIER.COLOR:
                    {
                        if (prop.GetValue() is Color c)
                        {
                            jw.BeginObject();
                            jw.WriteProperty("r", c.R);
                            jw.WriteProperty("g", c.G);
                            jw.WriteProperty("b", c.B);
                            jw.WriteProperty("hex", string.Format("#{0:X2}{1:X2}{2:X2}", c.R, c.G, c.B));
                            jw.EndObject();
                        }
                        else
                        {
                            jw.WriteNull();
                        }
                        break;
                    }
                case IDENTIFIER.MARGINS:
                    {
                        if (prop.GetValue() is Margins m)
                        {
                            jw.BeginObject();
                            jw.WriteProperty("cxLeftWidth", m.Left);
                            jw.WriteProperty("cxRightWidth", m.Right);
                            jw.WriteProperty("cyTopHeight", m.Top);
                            jw.WriteProperty("cyBottomHeight", m.Bottom);
                            jw.EndObject();
                        }
                        else
                        {
                            jw.WriteNull();
                        }
                        break;
                    }
                case IDENTIFIER.RECTTYPE:
                    {
                        if (prop.GetValue() is Margins m)
                        {
                            jw.BeginObject();
                            jw.WriteProperty("left", m.Left);
                            jw.WriteProperty("top", m.Top);
                            jw.WriteProperty("right", m.Right);
                            jw.WriteProperty("bottom", m.Bottom);
                            jw.EndObject();
                        }
                        else
                        {
                            jw.WriteNull();
                        }
                        break;
                    }
                case IDENTIFIER.POSITION:
                    {
                        if (prop.GetValue() is Size s)
                        {
                            jw.BeginObject();
                            jw.WriteProperty("cx", s.Width);
                            jw.WriteProperty("cy", s.Height);
                            jw.EndObject();
                        }
                        else
                        {
                            jw.WriteNull();
                        }
                        break;
                    }
                case IDENTIFIER.STRING:
                    {
                        string s = prop.GetValue() as string ?? "";
                        jw.WriteValue(s);
                        break;
                    }
                case IDENTIFIER.ENUM:
                case IDENTIFIER.HIGHCONTRASTCOLORTYPE:
                    {
                        int index = prop.GetValue() is int ev ? ev : 0;
                        var enumList = VisualStyleEnums.Find(prop.Header.nameID);
                        string enumName = null;
                        if (enumList != null && index >= 0 && index < enumList.Count)
                        {
                            enumName = enumList[index].Name;
                        }

                        jw.BeginObject();
                        jw.WriteProperty("value", index);
                        if (enumName != null)
                        {
                            jw.WriteProperty("enumName", enumName);
                        }
                        jw.EndObject();
                        break;
                    }
                case IDENTIFIER.INTLIST:
                    {
                        if (prop.GetValue() is List<int> list)
                        {
                            jw.BeginArray();
                            foreach (var item in list)
                            {
                                jw.WriteValue(item);
                            }
                            jw.EndArray();
                        }
                        else
                        {
                            jw.BeginArray();
                            jw.EndArray();
                        }
                        break;
                    }
                case IDENTIFIER.COLORLIST:
                    {
                        if (prop.GetValue() is List<Color> clist)
                        {
                            jw.BeginArray();
                            foreach (var c in clist)
                            {
                                jw.BeginObject();
                                jw.WriteProperty("r", c.R);
                                jw.WriteProperty("g", c.G);
                                jw.WriteProperty("b", c.B);
                                jw.EndObject();
                            }
                            jw.EndArray();
                        }
                        else
                        {
                            jw.BeginArray();
                            jw.EndArray();
                        }
                        break;
                    }
                case IDENTIFIER.FILENAME:
                case IDENTIFIER.FILENAME_LITE:
                    {
                        // shortFlag is the resource ID in IMAGE
                        int resId = prop.Header.shortFlag;
                        jw.BeginObject();
                        jw.WriteProperty("resourceId", resId);
                        jw.WriteProperty("resourceType", "IMAGE");
                        jw.EndObject();
                        break;
                    }
                case IDENTIFIER.DISKSTREAM:
                    {
                        // shortFlag is the resource ID in STREAM
                        int resId = prop.Header.shortFlag;
                        jw.BeginObject();
                        jw.WriteProperty("resourceId", resId);
                        jw.WriteProperty("resourceType", "STREAM");
                        jw.EndObject();
                        break;
                    }
                case IDENTIFIER.FONT:
                    {
                        int fontId = prop.Header.shortFlag;
                        jw.BeginObject();
                        jw.WriteProperty("fontId", fontId);
                        jw.EndObject();
                        break;
                    }
                default:
                    {
                        if (prop.GetValue() is byte[] bytes)
                        {
                            jw.WriteValue(BitConverter.ToString(bytes).Replace("-", ""));
                        }
                        else
                        {
                            jw.WriteValue(prop.GetValueAsString());
                        }
                        break;
                    }
            }
        }
    }

    /// <summary>
    /// Simple fast JSON writer formatting with 2-space indentation.
    /// </summary>
    class JsonWriter
    {
        private readonly StringBuilder sb = new StringBuilder(64 * 1024);
        private int indent = 0;
        private readonly Stack<bool> containerStack = new Stack<bool>(); // true = object, false = array
        private readonly Stack<int> elementCountStack = new Stack<int>();

        public void BeginObject()
        {
            PrepareValue();
            sb.Append("{\n");
            indent++;
            containerStack.Push(true);
            elementCountStack.Push(0);
        }

        public void EndObject()
        {
            indent--;
            containerStack.Pop();
            int count = elementCountStack.Pop();
            if (count > 0)
            {
                sb.Append("\n");
                WriteIndent();
            }
            sb.Append("}");
        }

        public void BeginArray()
        {
            PrepareValue();
            sb.Append("[\n");
            indent++;
            containerStack.Push(false);
            elementCountStack.Push(0);
        }

        public void EndArray()
        {
            indent--;
            containerStack.Pop();
            int count = elementCountStack.Pop();
            if (count > 0)
            {
                sb.Append("\n");
                WriteIndent();
            }
            sb.Append("]");
        }

        public void WritePropertyName(string name)
        {
            PrepareElement();
            sb.Append("\"");
            EscapeString(name, sb);
            sb.Append("\": ");
        }

        public void WriteProperty(string name, string value)
        {
            WritePropertyName(name);
            WriteValue(value);
        }

        public void WriteProperty(string name, int value)
        {
            WritePropertyName(name);
            WriteValue(value);
        }

        public void WriteProperty(string name, float value)
        {
            WritePropertyName(name);
            WriteValue(value);
        }

        public void WriteProperty(string name, bool value)
        {
            WritePropertyName(name);
            WriteValue(value);
        }

        public void WriteValue(string value)
        {
            PrepareValue();
            if (value == null)
            {
                sb.Append("null");
            }
            else
            {
                sb.Append("\"");
                EscapeString(value, sb);
                sb.Append("\"");
            }
        }

        public void WriteValue(int value)
        {
            PrepareValue();
            sb.Append(value);
        }

        public void WriteValue(float value)
        {
            PrepareValue();
            sb.Append(value.ToString("0.######", System.Globalization.CultureInfo.InvariantCulture));
        }

        public void WriteValue(bool value)
        {
            PrepareValue();
            sb.Append(value ? "true" : "false");
        }

        public void WriteNull()
        {
            PrepareValue();
            sb.Append("null");
        }

        private void PrepareElement()
        {
            if (elementCountStack.Count > 0)
            {
                int count = elementCountStack.Pop();
                if (count > 0)
                {
                    sb.Append(",\n");
                }
                elementCountStack.Push(count + 1);
                WriteIndent();
            }
        }

        private void PrepareValue()
        {
            if (containerStack.Count > 0 && !containerStack.Peek())
            {
                // In an array
                PrepareElement();
            }
        }

        private void WriteIndent()
        {
            for (int i = 0; i < indent; i++)
            {
                sb.Append("  ");
            }
        }

        private static void EscapeString(string s, StringBuilder output)
        {
            foreach (char c in s)
            {
                switch (c)
                {
                    case '\"': output.Append("\\\""); break;
                    case '\\': output.Append("\\\\"); break;
                    case '\b': output.Append("\\b"); break;
                    case '\f': output.Append("\\f"); break;
                    case '\n': output.Append("\\n"); break;
                    case '\r': output.Append("\\r"); break;
                    case '\t': output.Append("\\t"); break;
                    default:
                        if (c < 32 || c > 126)
                        {
                            output.AppendFormat("\\u{0:x4}", (int)c);
                        }
                        else
                        {
                            output.Append(c);
                        }
                        break;
                }
            }
        }

        public override string ToString()
        {
            return sb.ToString();
        }
    }
}

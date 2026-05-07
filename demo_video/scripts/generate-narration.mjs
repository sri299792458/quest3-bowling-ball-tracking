import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const baseUrl = (
  process.env.OPENAI_BASE_URL ||
  process.env.AZURE_OPENAI_ENDPOINT ||
  "https://api.openai.com/v1"
).replace(/\/$/, "");

const isAzureEndpoint = /openai\.azure\.com/i.test(baseUrl);
const apiKey =
  process.env.OPENAI_API_KEY ||
  process.env.AZURE_OPENAI_API_KEY ||
  process.env.AZURE_API_KEY;

if (!apiKey) {
  console.error("OPENAI_API_KEY or AZURE_OPENAI_API_KEY is not set.");
  console.error("Set it first, then run: npm run tts");
  process.exit(1);
}

const root = process.cwd();
const cuesPath = path.join(root, "scripts", "narration-cues.json");
const outputDir = path.join(root, "public", "audio");
const cues = JSON.parse(await readFile(cuesPath, "utf8"));

const model = process.env.OPENAI_TTS_MODEL || "gpt-4o-mini-tts";
const voice = process.env.OPENAI_TTS_VOICE || "marin";
const instructions =
  process.env.OPENAI_TTS_INSTRUCTIONS ||
  "Speak as a calm technical project narrator. Use a clear classroom presentation style, steady pace, and confident but not dramatic tone.";

await mkdir(outputDir, { recursive: true });

for (const cue of cues) {
  const outputPath = path.join(outputDir, cue.file);
  console.log(`Generating ${cue.file} (${cue.scene})...`);

  const headers = {
    "Content-Type": "application/json",
    ...(isAzureEndpoint ? { "api-key": apiKey } : { Authorization: `Bearer ${apiKey}` }),
  };

  const response = await fetch(`${baseUrl}/audio/speech`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      model,
      voice,
      input: cue.text,
      instructions,
      response_format: "mp3",
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`OpenAI TTS failed for ${cue.file}: ${response.status} ${body}`);
  }

  const buffer = Buffer.from(await response.arrayBuffer());
  await writeFile(outputPath, buffer);
}

console.log(`Generated ${cues.length} narration clips in ${outputDir}`);

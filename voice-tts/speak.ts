import { execFile } from "node:child_process";
import { unlinkSync } from "node:fs";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

/**
 * Speak pi's full reply aloud using Microsoft Edge TTS (晓晓 zh-CN-XiaoxiaoNeural).
 * Reads both Chinese and English. Same engine as the OpenClaw TTS server.
 * - Override voice: PI_SPEAK_VOICE (e.g. en-US-AriaNeural)
 * - Disable: PI_SPEAK_OFF=1
 */
export default function (pi: ExtensionAPI) {
  if (process.env.PI_SPEAK_OFF) return;

  const EDGE_TTS = process.env.EDGE_TTS_BIN ?? "edge-tts"; // portable: resolve from PATH (override with EDGE_TTS_BIN=/path/to/edge-tts)
  const VOICE = process.env.PI_SPEAK_VOICE ?? "zh-CN-XiaoxiaoNeural";
  const MAX_CHUNK = 2000; // edge-tts per-request limit

  /** Strip Markdown syntax so TTS reads clean, natural text (not symbols). */
  const cleanForTTS = (text: string): string => {
    let t = text;
    // code blocks -> short marker
    t = t.replace(/```[\s\S]*?```/g, " 代码省略。 ");
    // inline code -> keep inner text
    t = t.replace(/`([^`]+)`/g, "$1");
    // images ![alt](url) -> alt text
    t = t.replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1");
    // links [text](url) -> text only
    t = t.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
    // headings # ## ### -> text only
    t = t.replace(/^#{1,6}\s*/gm, "");
    // bold/italic *** ** * ___ __ _
    t = t.replace(/\*\*\*([^*]+)\*\*\*/g, "$1");
    t = t.replace(/\*\*([^*]+)\*\*/g, "$1");
    t = t.replace(/\*([^*]+)\*/g, "$1");
    t = t.replace(/___([^_]+)___/g, "$1");
    t = t.replace(/__([^_]+)__/g, "$1");
    t = t.replace(/(?<![\w])_([^_]+)_(?![\w])/g, "$1");
    // blockquotes >
    t = t.replace(/^\s*>\s?/gm, "");
    // list markers - * + 1. 1) •
    t = t.replace(/^\s*[-*+•]\s+/gm, "");
    t = t.replace(/^\s*\d+[.)]\s+/gm, "");
    // horizontal rules --- *** ___
    t = t.replace(/^\s*(---|\*\*\*|___)\s*$/gm, "");
    // table pipes -> spaces (drop separator rows)
    t = t.replace(/^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/gm, "");
    t = t.replace(/\|/g, " ");
    // emoji & decorative symbols (faces, flags, dingbats, arrows, shapes...)
    t = t.replace(
      /[\u{1F000}-\u{1FAFF}\u{1F1E6}-\u{1F1FF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2190}-\u{21FF}\u{25A0}-\u{25FF}\u{FE0F}\u{200D}\u{20E3}\u{00A9}\u{00AE}\u{2122}]/gu,
      ""
    );
    // remaining underscores -> space (so file_name reads as "file name", not "underscore")
    t = t.replace(/_/g, " ");
    // speaker name -> first person (voice should not refer to itself as 晓晓/Xiaoxiao)
    t = t.replace(/Xiaoxiao's/gi, "My");
    t = t.replace(/Xiaoxiao/gi, "I");
    t = t.replace(/晓晓/g, "我");
    // collapse whitespace
    t = t.replace(/[ \t]+/g, " ");
    t = t.replace(/\n{3,}/g, "\n\n");
    return t.trim();
  };

  let chain: Promise<void> = Promise.resolve();

  const speakChunk = (text: string) =>
    new Promise<void>((resolve) => {
      const tmp = `/tmp/pi-speak-${Date.now()}-${Math.random().toString(36).slice(2)}.mp3`;
      execFile(
        EDGE_TTS,
        ["--voice", VOICE, "--text", text, "--write-media", tmp, "--write-subtitles", "/dev/null"],
        { timeout: 60000 },
        (err) => {
          if (err) {
            console.error("[speak] edge-tts:", err.message);
            return resolve();
          }
          execFile("/usr/bin/afplay", [tmp], { timeout: 300000 }, () => {
            try { unlinkSync(tmp); } catch { /* ignore */ }
            resolve();
          });
        }
      );
    });

  const speakText = (text: string) => {
    const chunks: string[] = [];
    for (let i = 0; i < text.length; i += MAX_CHUNK) chunks.push(text.slice(i, i + MAX_CHUNK));
    chain = chain.then(() => chunks.reduce((p, c) => p.then(() => speakChunk(c)), Promise.resolve()));
  };

  pi.on("agent_end", async (event, _ctx) => {
    if (event.willRetry) return; // retry will re-run; skip intermediate

    const messages = event.messages ?? [];
    // take ONLY the final assistant message (the last one that has text)
    let final: string | null = null;
    for (let i = messages.length - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg.role !== "assistant") continue;
      const text = (msg.content ?? [])
        .filter((b) => b.type === "text")
        .map((b) => b.text)
        .join("\n")
        .trim();
      if (!text) continue;
      final = text;
      break;
    }
    if (final) speakText(cleanForTTS(final));
  });
}

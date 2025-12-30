type EditDistanceOptions = {
  maxDistance: number;
};

function normalize(text: string): string {
  return String(text || "")
    .trim()
    .toLowerCase()
    .replace(/[\u2019]/g, "'")
    .replace(/[^\p{L}\p{N}\s'’-]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function editDistanceWithin(a: string, b: string, options: EditDistanceOptions): boolean {
  const maxDistance = options.maxDistance;
  if (a === b) return true;
  const alen = a.length;
  const blen = b.length;
  if (Math.abs(alen - blen) > maxDistance) return false;
  if (alen === 0) return blen <= maxDistance;
  if (blen === 0) return alen <= maxDistance;

  const prev = new Array(blen + 1);
  const curr = new Array(blen + 1);
  for (let j = 0; j <= blen; j++) prev[j] = j;

  for (let i = 1; i <= alen; i++) {
    curr[0] = i;
    let rowMin = curr[0];
    const ca = a.charCodeAt(i - 1);
    for (let j = 1; j <= blen; j++) {
      const cost = ca === b.charCodeAt(j - 1) ? 0 : 1;
      curr[j] = Math.min(
        prev[j] + 1,
        curr[j - 1] + 1,
        prev[j - 1] + cost
      );
      if (curr[j] < rowMin) rowMin = curr[j];
    }
    if (rowMin > maxDistance) return false;
    for (let j = 0; j <= blen; j++) prev[j] = curr[j];
  }
  return prev[blen] <= maxDistance;
}

export function isSemanticYes(text: string): boolean {
  const raw = String(text || "");
  if (/[👍✅✔]/.test(raw)) return true;

  const normalized = normalize(text);
  if (!normalized) return false;

  if (/\b(but|however|except|unless)\b/.test(normalized)) return false;
  if (/\b(no|nope|nah|not really|not quite|wrong|incorrect|off)\b/.test(normalized))
    return false;
  if (/\b(change|edit|adjust|fix|revise|update)\b/.test(normalized)) return false;
  if (/\b(maybe|not sure|unsure|i don't know|i dont know|idk)\b/.test(normalized))
    return false;
  if (/\b(nah)\b/.test(normalized)) return false;

  const compact = normalized.replace(/\s+/g, " ").trim();
  if (
    /\b(yes|yep|yeah|yup|sure|sure thing|ok|okay|k|kk|agree|agreed|correct|confirmed|confirm|sounds good|looks good|sounds right|looks right|that looks right|this looks right|that's right|thats right|all good|good to go|go ahead|proceed|continue|move on)\b/.test(
      compact
    )
  )
    return true;

  if (compact.startsWith("confir")) return true;
  if (compact.startsWith("ye")) return true;

  const tokens = compact.split(" ").filter(Boolean);
  for (const token of tokens) {
    if (token === "ok" || token === "k") return true;
    if (token.length < 2) continue;
    if (editDistanceWithin(token, "agree", { maxDistance: 1 })) return true;
    if (editDistanceWithin(token, "confirm", { maxDistance: 2 })) return true;
    if (editDistanceWithin(token, "confirmed", { maxDistance: 2 })) return true;
    if (editDistanceWithin(token, "correct", { maxDistance: 1 })) return true;
    if (editDistanceWithin(token, "okay", { maxDistance: 1 })) return true;
    if (editDistanceWithin(token, "yes", { maxDistance: 1 })) return true;
    if (editDistanceWithin(token, "yeah", { maxDistance: 1 })) return true;
  }

  return false;
}

export type ConfirmationDecision = "proceed" | "refine" | "clarify";

export function decideConfirmation(text: string): ConfirmationDecision {
  const raw = String(text || "").trim();
  if (!raw) return "clarify";

  const normalized = normalize(raw);
  if (!normalized) return "clarify";

  // Explicit disagreement -> refine.
  if (
    /\b(no|nope|nah|disagree|dont agree|don't agree|wrong|incorrect|inaccurate|not accurate|not right|doesnt look right|doesn't look right|not really|not quite)\b/.test(
      normalized
    )
  )
    return "refine";

  // Requests changes -> refine (but allow "no changes" / "nothing to change" as proceed).
  if (
    /\b(no|none|nothing)\s+(to\s+)?(change|changes|edit|edits|adjust|adjustments|fix|fixes|revise|revision|update|updates|tweak|tweaks)\b/.test(
      normalized
    )
  )
    return "proceed";
  if (/\b(change|changes|edit|adjust|fix|revise|update|tweak|correction|correct this)\b/.test(normalized))
    return "refine";

  // Uncertainty -> clarify.
  if (
    /\b(maybe|not sure|unsure|uncertain|depends|idk|i dont know|i don't know|i think so|probably|guess|kinda|kind of|sort of)\b/.test(
      normalized
    )
  )
    return "clarify";

  // Questions -> usually clarify, but treat "let's move on?" / "all good?" as proceed.
  if (raw.includes("?")) {
    if (
      /\b(move on|proceed|continue|all good|good to go|ready|ok|okay|sounds good|looks good|we good|we're good|we are good)\b/.test(
        normalized
      )
    )
      return "proceed";
    return "clarify";
  }
  if (/\b(but|however|except|unless)\b/.test(normalized)) return "clarify";

  // Objection-first default: proceed.
  return "proceed";
}

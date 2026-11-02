// Display-only label for a Del Monte category path (2026-10-26): the raw
// "/SWEET SPAG SAUCE/PROMO" reads as "Sweet Spag Sauce · Promo". Keys, links
// and API calls keep the raw value; nothing here is sent back.

const titleWord = (word) => {
  if (!word) return word;
  // Only an all-caps word is re-cased; "Del Monte" etc. stays as written.
  if (word !== word.toUpperCase()) return word;
  return word.charAt(0) + word.slice(1).toLowerCase();
};

// Title-case each word of one part, keeping its spacing and punctuation
// ("100%", "ACE - BASE REGULAR").
const titlePart = (part) => part.replace(/[A-Za-z][A-Za-z']*/g, titleWord);

export function categoryLabel(raw) {
  if (raw == null) return raw;
  const text = String(raw).trim();
  if (!text) return text;
  const parts = text.split('/').map((p) => p.trim()).filter(Boolean);
  if (parts.length === 0) return text;
  return parts.map(titlePart).join(' · ');
}

export default categoryLabel;

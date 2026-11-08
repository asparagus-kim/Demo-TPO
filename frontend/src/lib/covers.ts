/** Deterministic artwork mapping for tracks — covers live in public/image/cover-NN.jpg.
 *  Covers 01–10 are the moody / music-appropriate shots and are preferred for tracks;
 *  11–26 are used for shelf tiles and as collision spill-over. */

const TRACK_COVER_COUNT = 10
const TOTAL_COVER_COUNT = 26

export function coverSrc(n: number): string {
  const clamped = Math.min(Math.max(n, 1), TOTAL_COVER_COUNT)
  return `/image/cover-${String(clamped).padStart(2, "0")}.jpg`
}

/** Stable non-crypto hash so a given track_id always lands on the same cover. */
function hashId(id: string): number {
  let h = 0
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

/** Assign a unique cover per track for one playlist.
 *  Start bucket = hash(track_id) into the moody 01–10 range; on collision,
 *  probe forward through 01–10 first, then spill into 11–26. Deterministic
 *  for a given ordered track list. */
export function assignCovers(trackIds: string[]): Map<string, string> {
  const used = new Set<number>()
  const result = new Map<string, string>()

  for (const id of trackIds) {
    const start = hashId(id) % TRACK_COVER_COUNT
    const candidates = [
      ...Array.from(
        { length: TRACK_COVER_COUNT },
        (_, k) => ((start + k) % TRACK_COVER_COUNT) + 1
      ),
      ...Array.from(
        { length: TOTAL_COVER_COUNT - TRACK_COVER_COUNT },
        (_, k) => TRACK_COVER_COUNT + 1 + k
      ),
    ]
    const pick = candidates.find((c) => !used.has(c)) ?? start + 1
    used.add(pick)
    result.set(id, coverSrc(pick))
  }
  return result
}

/** Covers for promo / shelf tiles (scenic 11–26 range). */
export function shelfCover(index: number): string {
  const span = TOTAL_COVER_COUNT - TRACK_COVER_COUNT
  return coverSrc(TRACK_COVER_COUNT + 1 + (Math.abs(index) % span))
}

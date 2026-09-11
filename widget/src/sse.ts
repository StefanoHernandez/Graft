/**
 * Incremental SSE parser.
 *
 * A chunk boundary can land anywhere: between two frames, inside a field name,
 * or in the middle of a multi-byte character. So bytes are decoded with a
 * streaming decoder and frames are only emitted once their blank line arrives.
 */
export interface SseEvent {
  event: string;
  data: string;
}

export function createSseParser(onEvent: (event: SseEvent) => void) {
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  function flush(block: string): void {
    let name = "message";
    const data: string[] = [];
    for (const rawLine of block.split("\n")) {
      const line = rawLine.replace(/\r$/, "");
      // A line starting with ':' is a comment — heartbeats arrive this way.
      if (line === "" || line.startsWith(":")) continue;
      const separator = line.indexOf(":");
      const field = separator === -1 ? line : line.slice(0, separator);
      let value = separator === -1 ? "" : line.slice(separator + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") name = value;
      // Several data lines in one frame join with a newline, per the spec.
      else if (field === "data") data.push(value);
    }
    if (data.length > 0) onEvent({ event: name, data: data.join("\n") });
  }

  return {
    push(chunk: Uint8Array): void {
      buffer += decoder.decode(chunk, { stream: true });
      let boundary = findBoundary(buffer);
      while (boundary !== null) {
        flush(buffer.slice(0, boundary.index));
        buffer = buffer.slice(boundary.index + boundary.length);
        boundary = findBoundary(buffer);
      }
    },
  };
}

function findBoundary(text: string): { index: number; length: number } | null {
  const lf = text.indexOf("\n\n");
  const crlf = text.indexOf("\r\n\r\n");
  if (crlf !== -1 && (lf === -1 || crlf < lf)) return { index: crlf, length: 4 };
  if (lf !== -1) return { index: lf, length: 2 };
  return null;
}

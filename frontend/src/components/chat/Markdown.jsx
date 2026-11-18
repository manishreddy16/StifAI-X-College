import React from "react";

// Inline formatting: **bold**, *italic*, `code`, [text](https://link) and bare https:// URLs.
export function InlineMarkdown({ text }) {
  const pattern = /(\*\*.+?\*\*|\*.+?\*|`.+?`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s)]+)/g;
  return String(text).split(pattern).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) return <em key={index}>{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) return <code key={index}>{part.slice(1, -1)}</code>;
    const link = part.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
    if (link) return <a key={index} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>;
    if (/^https?:\/\//.test(part)) return <a key={index} href={part} target="_blank" rel="noreferrer">{part}</a>;
    return part;
  });
}

const parseCells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());

/**
 * Renders the assistant's Markdown-ish answer: headings (#–###), bullet and numbered lists,
 * tables, fenced code blocks, block quotes, inline bold/italic/code/links.
 */
export function MarkdownAnswer({ text }) {
  const lines = String(text || "").replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let items = [];
  let listType = "ul";
  let tableRows = [];
  let code = null; // { lang, lines } while inside a fenced block
  let quote = [];

  const flushList = () => {
    if (!items.length) return;
    const Tag = listType;
    blocks.push(<Tag key={`list-${blocks.length}`}>{items.map((item, i) => <li key={i}><InlineMarkdown text={item} /></li>)}</Tag>);
    items = [];
  };
  const flushQuote = () => {
    if (!quote.length) return;
    blocks.push(<blockquote key={`quote-${blocks.length}`}><InlineMarkdown text={quote.join(" ")} /></blockquote>);
    quote = [];
  };
  const flushTable = () => {
    if (!tableRows.length) return;
    const cleaned = tableRows.filter((row) => !row.every((cell) => /^:?-{2,}:?$/.test(cell)));
    if (cleaned.length) {
      const headers = cleaned[0];
      const rows = cleaned.slice(1);
      blocks.push(
        <div className="answer-table-wrap" key={`table-${blocks.length}`} tabIndex={0} role="region" aria-label="Table, scrollable">
          <table className="answer-table">
            <thead><tr>{headers.map((cell, i) => <th key={i} scope="col"><InlineMarkdown text={cell} /></th>)}</tr></thead>
            <tbody>
              {rows.map((row, ri) => (
                <tr key={ri}>{headers.map((_, ci) => <td key={ci}><InlineMarkdown text={row[ci] || "—"} /></td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    tableRows = [];
  };
  const flushAll = () => { flushList(); flushTable(); flushQuote(); };

  lines.forEach((raw, i) => {
    const trimmed = raw.trim();

    // Fenced code blocks
    if (code) {
      if (trimmed.startsWith("```")) {
        blocks.push(<pre key={`code-${i}`} tabIndex={0}><code>{code.lines.join("\n")}</code></pre>);
        code = null;
      } else code.lines.push(raw);
      return;
    }
    if (trimmed.startsWith("```")) { flushAll(); code = { lang: trimmed.slice(3).trim(), lines: [] }; return; }

    const isTableRow = trimmed.includes("|") && trimmed.split("|").length >= 3;
    if (isTableRow) { flushList(); flushQuote(); tableRows.push(parseCells(trimmed)); return; }
    flushTable();

    const quoted = trimmed.match(/^>\s?(.*)$/);
    if (quoted) { flushList(); quote.push(quoted[1]); return; }
    flushQuote();

    const bullet = trimmed.match(/^(?:([-*•])|(\d+[.)]))\s+(.+)$/);
    if (bullet) {
      const type = bullet[2] ? "ol" : "ul";
      if (items.length && type !== listType) flushList();
      listType = type;
      items.push(bullet[3]);
      return;
    }
    flushList();
    if (!trimmed) return;

    if (/^(-{3,}|\*{3,})$/.test(trimmed)) { blocks.push(<hr key={i} />); return; }

    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const content = <InlineMarkdown text={heading[2]} />;
      const level = heading[1].length;
      blocks.push(level === 1 ? <h3 key={i}>{content}</h3> : level === 2 ? <h4 key={i}>{content}</h4> : <h5 key={i}>{content}</h5>);
    } else {
      blocks.push(<p key={i}><InlineMarkdown text={trimmed} /></p>);
    }
  });
  if (code) blocks.push(<pre key="code-open" tabIndex={0}><code>{code.lines.join("\n")}</code></pre>);
  flushAll();
  return <div className="markdown-answer">{blocks}</div>;
}

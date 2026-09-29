import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownRendererProps {
  content: string;
  className?: string;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  className = "",
}) => {
  return (
    <div className={`markdown-content text-sm leading-relaxed ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => (
            <h1 className="text-base font-bold text-ink-950 mt-3 mb-2 first:mt-0 border-b border-ink-100 pb-1">
              {children}
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-sm font-bold text-ink-900 mt-2.5 mb-1.5 first:mt-0">
              {children}
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-xs font-semibold text-ink-900 mt-2 mb-1 first:mt-0">
              {children}
            </h3>
          ),
          p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
          strong: ({ children }) => <strong className="font-bold text-ink-950">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          ul: ({ children }) => (
            <ul className="list-disc pl-5 mb-2.5 space-y-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 mb-2.5 space-y-1">{children}</ol>
          ),
          li: ({ children }) => <li className="leading-relaxed pl-0.5">{children}</li>,
          table: ({ children, ...props }) => (
            <div className="overflow-x-auto my-3 rounded-lg border border-ink-200 shadow-xs">
              <table className="min-w-full divide-y divide-ink-200 text-xs" {...props}>
                {children}
              </table>
            </div>
          ),
          thead: ({ children, ...props }) => (
            <thead className="bg-ink-100/80 font-semibold text-ink-800" {...props}>{children}</thead>
          ),
          tbody: ({ children, ...props }) => (
            <tbody className="divide-y divide-ink-100 bg-white" {...props}>{children}</tbody>
          ),
          tr: ({ children, ...props }) => (
            <tr className="hover:bg-ink-50/60 transition-colors" {...props}>{children}</tr>
          ),
          th: ({ children, style, className = "", ...props }) => {
            const alignClass =
              style?.textAlign === "right"
                ? "text-right"
                : style?.textAlign === "center"
                ? "text-center"
                : "text-left";
            return (
              <th
                style={style}
                className={`px-3 py-2 font-semibold text-ink-800 whitespace-nowrap ${alignClass} ${className}`}
                {...props}
              >
                {children}
              </th>
            );
          },
          td: ({ children, style, className = "", ...props }) => {
            const alignClass =
              style?.textAlign === "right"
                ? "text-right"
                : style?.textAlign === "center"
                ? "text-center"
                : "text-left";
            return (
              <td
                style={style}
                className={`px-3 py-1.5 text-ink-700 font-data ${alignClass} ${className}`}
                {...props}
              >
                {children}
              </td>
            );
          },
          blockquote: ({ children }) => (
            <blockquote className="border-l-3 border-seal-400 pl-3 py-1 my-2 italic text-ink-600 bg-ink-50/50 rounded-r">
              {children}
            </blockquote>
          ),
          code: ({ className: codeClassName, children, ...props }) => {
            const isInline = !codeClassName && !String(children).includes("\n");
            if (isInline) {
              return (
                <code
                  className="rounded bg-ink-100 px-1.5 py-0.5 font-mono text-[11px] text-ink-800 border border-ink-200"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <pre className="overflow-x-auto rounded-lg bg-ink-950 p-3 font-mono text-xs text-ink-50 my-2.5">
                <code className={codeClassName} {...props}>
                  {children}
                </code>
              </pre>
            );
          },
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-seal-600 underline underline-offset-2 font-medium hover:text-seal-700 transition-colors"
            >
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
};

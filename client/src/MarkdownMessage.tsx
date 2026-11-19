import { isValidElement, useEffect, useRef, useState, type ReactNode } from 'react';
import { CheckOutlined, CopyOutlined } from '@ant-design/icons';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeSanitize from 'rehype-sanitize';
import { PrismAsyncLight as SyntaxHighlighter } from 'react-syntax-highlighter';
import { codeLanguageFromClass, codeLanguageLabel, syntaxLanguage } from './markdown';

function textOf(value: ReactNode): string {
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map(textOf).join('');
  if (isValidElement(value)) return textOf((value.props as { children?: ReactNode }).children);
  return '';
}

async function writeClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
}

function useCopy() {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const copy = async (text: string) => {
    await writeClipboard(text);
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 1400);
  };
  return { copied, copy };
}

function CodeBlock({ code, language }: { code: string; language: string }) {
  const { copied, copy } = useCopy();
  return <div className="md-code">
    <div className="md-code-head">
      <span>{codeLanguageLabel(language)}</span>
      <button type="button" aria-label="复制代码" onClick={() => void copy(code)}>
        {copied ? <CheckOutlined aria-hidden="true" /> : <CopyOutlined aria-hidden="true" />}
        {copied ? '已复制' : '复制'}
      </button>
    </div>
    <SyntaxHighlighter language={syntaxLanguage(language)} useInlineStyles={false} PreTag="pre" CodeTag="code">{code}</SyntaxHighlighter>
  </div>;
}

const components: Components = {
  pre({ children }) {
    const child = Array.isArray(children) ? children[0] : children;
    if (!isValidElement(child)) return <pre>{children}</pre>;
    const props = child.props as { className?: string; children?: ReactNode };
    return <CodeBlock code={textOf(props.children).replace(/\n$/, '')} language={codeLanguageFromClass(props.className)} />;
  },
  code({ children }) {
    return <code className="md-inline-code">{children}</code>;
  },
  a({ href, children }) {
    return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
  },
  table({ children }) {
    return <div className="md-table-wrap"><table>{children}</table></div>;
  },
  img({ src, alt }) {
    return <img src={src} alt={alt || ''} loading="lazy" />;
  },
};

export function MarkdownMessage({ text }: { text: string }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]} components={components}>{text || ''}</ReactMarkdown>;
}

export function CopyReplyButton({ text }: { text: string }) {
  const { copied, copy } = useCopy();
  return <button type="button" className="reply-copy" aria-label="复制回复" title={copied ? '已复制' : '复制回复'} onClick={() => void copy(text)}>
    {copied ? <CheckOutlined aria-hidden="true" /> : <CopyOutlined aria-hidden="true" />}
    <span className="reply-copy-label">{copied ? '已复制' : '复制回复'}</span>
  </button>;
}

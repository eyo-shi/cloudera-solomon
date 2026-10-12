import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { useTabStore } from "../../stores/tabStore";
import {
  isSearchDocumentLink,
  openSearchDocumentFromLink,
} from "./openSearchDocumentFromLink";
import {
  isGraphCypherLink,
  openGraphCypherFromLink,
  parseGraphCypherLink,
} from "./openGraphCypherFromLink";

interface Props {
  children: string;
}

export function ChatMarkdown({ children }: Props) {
  const openTab = useTabStore((s) => s.openTab);

  const components: Components = {
    a: ({ href, children: linkChildren, ...rest }) => {
      if (isSearchDocumentLink(href)) {
        return (
          <button
            type="button"
            className="chat-search-doc-link"
            onClick={(e) => {
              e.preventDefault();
              void openSearchDocumentFromLink(href!, openTab);
            }}
          >
            {linkChildren}
          </button>
        );
      }
      if (isGraphCypherLink(href)) {
        const payload = parseGraphCypherLink(href!);
        const cypherText = payload?.cypher ?? String(linkChildren);
        return (
          <button
            type="button"
            className="chat-graph-cypher-panel"
            title="Graph タブで実行"
            onClick={(e) => {
              e.preventDefault();
              openGraphCypherFromLink(href!);
            }}
          >
            <pre className="chat-graph-cypher-panel__pre">
              <code className="language-cypher">{cypherText}</code>
            </pre>
          </button>
        );
      }
      return (
        <a href={href} {...rest} target="_blank" rel="noreferrer">
          {linkChildren}
        </a>
      );
    },
  };

  return (
    <Markdown remarkPlugins={[remarkGfm]} components={components}>
      {children}
    </Markdown>
  );
}

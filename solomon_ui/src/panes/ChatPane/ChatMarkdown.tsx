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
import {
  isSolomonAppLink,
  normalizeSolomonHref,
  preserveSolomonUrlTransform,
} from "./solomonAppLinks";

interface Props {
  children: string;
}

export function ChatMarkdown({ children }: Props) {
  const openTab = useTabStore((s) => s.openTab);

  const components: Components = {
    a: ({ href, children: linkChildren, ...rest }) => {
      const solomonHref = normalizeSolomonHref(href);
      if (isSearchDocumentLink(solomonHref)) {
        return (
          <button
            type="button"
            className="chat-search-doc-link"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              void openSearchDocumentFromLink(solomonHref!, openTab);
            }}
          >
            {linkChildren}
          </button>
        );
      }
      if (isGraphCypherLink(solomonHref)) {
        const payload = parseGraphCypherLink(solomonHref!);
        const cypherText = payload?.cypher ?? String(linkChildren);
        return (
          <button
            type="button"
            className="chat-graph-cypher-panel"
            title="Graph タブで実行"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              openGraphCypherFromLink(solomonHref!);
            }}
          >
            <pre className="chat-graph-cypher-panel__pre">
              <code className="language-cypher">{cypherText}</code>
            </pre>
          </button>
        );
      }
      const safeHref = solomonHref?.trim() ?? href?.trim() ?? "";
      if (!safeHref || isSolomonAppLink(safeHref)) {
        return <span>{linkChildren}</span>;
      }
      const external =
        safeHref.startsWith("http://") || safeHref.startsWith("https://");
      return (
        <a
          href={safeHref}
          {...rest}
          {...(external
            ? { target: "_blank", rel: "noreferrer" }
            : { target: undefined, rel: undefined })}
        >
          {linkChildren}
        </a>
      );
    },
  };

  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      urlTransform={preserveSolomonUrlTransform}
      components={components}
    >
      {children}
    </Markdown>
  );
}

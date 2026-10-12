import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { useTabStore } from "../../stores/tabStore";
import {
  isSearchDocumentLink,
  openSearchDocumentFromLink,
} from "./openSearchDocumentFromLink";

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

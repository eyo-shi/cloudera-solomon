/**
 * Graph 表示エリア右上 — Search / Download / Details (Neo4j Browser 風)。
 */
import { useEffect, useRef } from "react";
import type { GraphCanvasHandle } from "./GraphCanvas";

interface Props {
  searchOpen: boolean;
  searchQuery: string;
  sidebarOpen: boolean;
  downloadMenuOpen: boolean;
  canvasRef: React.RefObject<GraphCanvasHandle | null>;
  onSearchOpenChange: (open: boolean) => void;
  onSearchQueryChange: (query: string) => void;
  onSidebarOpenChange: (open: boolean) => void;
  onDownloadMenuOpenChange: (open: boolean) => void;
}

function IconSearch() {
  return (
    <svg className="graph-canvas-topbar__svg" viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="6.5" cy="6.5" r="3.75" fill="none" stroke="currentColor" strokeWidth="1.25" />
      <path d="M9.5 9.5 13 13" stroke="currentColor" strokeWidth="1.25" strokeLinecap="round" />
    </svg>
  );
}

function IconDownload() {
  return (
    <svg className="graph-canvas-topbar__svg" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M8 2.5v7M5.5 7 8 9.5 10.5 7"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M3.5 13.5h9"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconDetails() {
  return (
    <svg className="graph-canvas-topbar__svg" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M4.5 2.5h6.5l1.5 1.5V13.5H4.5V2.5z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinejoin="round"
      />
      <path d="M11 2.5v1.5h1.5" fill="none" stroke="currentColor" strokeWidth="1.1" />
      <path d="M6.5 7h4M6.5 9.5h4" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}

export function GraphCanvasTopbar({
  searchOpen,
  searchQuery,
  sidebarOpen,
  downloadMenuOpen,
  canvasRef,
  onSearchOpenChange,
  onSearchQueryChange,
  onSidebarOpenChange,
  onDownloadMenuOpenChange,
}: Props) {
  const searchInputRef = useRef<HTMLInputElement>(null);
  const downloadMenuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (searchOpen) searchInputRef.current?.focus();
  }, [searchOpen]);

  useEffect(() => {
    if (!downloadMenuOpen) return;
    function onPointerDown(e: MouseEvent) {
      if (!downloadMenuRef.current?.contains(e.target as Node)) {
        onDownloadMenuOpenChange(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [downloadMenuOpen, onDownloadMenuOpenChange]);

  function closeSearch() {
    onSearchQueryChange("");
    onSearchOpenChange(false);
  }

  return (
    <div className="graph-canvas-topbar">
      <div
        className={
          "graph-canvas-topbar__search" +
          (searchOpen ? " graph-canvas-topbar__search--open" : "")
        }
      >
        {searchOpen ? (
          <>
            <IconSearch />
            <input
              ref={searchInputRef}
              className="graph-canvas-topbar__search-input"
              type="search"
              value={searchQuery}
              placeholder="Search..."
              spellCheck={false}
              onChange={(e) => onSearchQueryChange(e.target.value)}
            />
            <button
              type="button"
              className="graph-canvas-topbar__search-clear"
              title="Close search"
              aria-label="Close search"
              onClick={closeSearch}
            >
              ×
            </button>
          </>
        ) : (
          <button
            type="button"
            className="graph-canvas-topbar__btn"
            title="Search"
            aria-label="Search"
            onClick={() => onSearchOpenChange(true)}
          >
            <IconSearch />
          </button>
        )}
      </div>
      <div className="graph-canvas-topbar__actions">
        <div className="graph-canvas-topbar__download" ref={downloadMenuRef}>
          <button
            type="button"
            className="graph-canvas-topbar__btn"
            title="Download"
            aria-label="Download"
            aria-expanded={downloadMenuOpen}
            onClick={() => onDownloadMenuOpenChange(!downloadMenuOpen)}
          >
            <IconDownload />
          </button>
          {downloadMenuOpen && (
            <div className="graph-canvas-download-menu" role="menu">
              <button
                type="button"
                role="menuitem"
                className="graph-canvas-download-menu__item"
                onClick={() => {
                  canvasRef.current?.downloadPng();
                  onDownloadMenuOpenChange(false);
                }}
              >
                Download as PNG
              </button>
              <button
                type="button"
                role="menuitem"
                className="graph-canvas-download-menu__item"
                onClick={() => {
                  canvasRef.current?.downloadSvg();
                  onDownloadMenuOpenChange(false);
                }}
              >
                Download as SVG
              </button>
            </div>
          )}
        </div>
        <button
          type="button"
          className={
            "graph-canvas-topbar__btn" +
            (sidebarOpen ? " graph-canvas-topbar__btn--active" : "")
          }
          title={sidebarOpen ? "Hide details panel" : "Show details panel"}
          aria-label={sidebarOpen ? "Hide details panel" : "Show details panel"}
          aria-pressed={sidebarOpen}
          onClick={() => onSidebarOpenChange(!sidebarOpen)}
        >
          <IconDetails />
        </button>
      </div>
    </div>
  );
}

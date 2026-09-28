/**
 * s3 バケットのブラウザ。
 *
 * データ構造 (すべて prefix 単位で lazy):
 *   bucket (root)
 *     └ subfolder (勾配区切り、末尾 '/' 付き)
 *         └ ... 再帰
 *     └ object (leaf, click で FilePreviewTab を開く)
 *
 * バケット直下だけを最初にロードし、subfolder を展開したら都度 useS3List。
 */
import { useEffect, useMemo, useState } from "react";
import { useS3List } from "../../api/files";
import { useTabStore } from "../../stores/tabStore";
import { useChatStore } from "../../stores/chatStore";
import { FileTypeIcon } from "./FileTypeIcon";
import { IconChevronToggle } from "./ExplorerIcons";
import { NodeMenu } from "./NodeMenu";

interface S3TreeProps {
  bucket: string;
  filter: string;
}

interface ActiveFileSelection {
  bucket: string;
  key: string;
}

function useActiveFileSelection(): ActiveFileSelection | null {
  return useTabStore((s) => {
    const tab = s.tabs.find((t) => t.id === s.activeId);
    if (tab?.kind !== "file_preview") return null;
    const bucket = tab.ref.bucket;
    const key = tab.ref.key;
    if (typeof bucket !== "string" || typeof key !== "string") return null;
    return { bucket, key };
  });
}

/** 選択ファイルの祖先 prefix (末尾 `/` 付き) を列挙する。 */
function prefixesAlongKey(key: string): string[] {
  const parts = key.split("/").filter(Boolean);
  if (parts.length <= 1) return [];
  const prefixes: string[] = [];
  let acc = "";
  for (let i = 0; i < parts.length - 1; i += 1) {
    acc += `${parts[i]}/`;
    prefixes.push(acc);
  }
  return prefixes;
}

export function S3Tree({ bucket, filter }: S3TreeProps) {
  const selection = useActiveFileSelection();
  const isSelectedInBucket = selection?.bucket === bucket;
  const selectedKey = isSelectedInBucket ? selection!.key : null;
  const autoExpandPrefixes = useMemo(
    () =>
      selectedKey ? new Set(prefixesAlongKey(selectedKey)) : new Set<string>(),
    [selectedKey],
  );

  const [menuFor, setMenuFor] = useState<
    | {
        x: number;
        y: number;
        kind: "object";
        bucket: string;
        key: string;
        name: string;
      }
    | null
  >(null);
  const [rootExpanded, setRootExpanded] = useState(false);

  useEffect(() => {
    if (isSelectedInBucket) setRootExpanded(true);
  }, [isSelectedInBucket, selectedKey]);

  return (
    <ul className="tree-list" onClick={() => setMenuFor(null)}>
      <li className="tree-node">
        <div
          className={
            "tree-row tree-row--schema tree-row--bucket" +
            (isSelectedInBucket ? " tree-row--path" : "")
          }
          onClick={() => setRootExpanded((v) => !v)}
        >
          <span className="tree-caret">
            <IconChevronToggle expanded={rootExpanded} />
          </span>
          <span className="tree-label">{bucket}</span>
        </div>
        {rootExpanded && (
          <S3PrefixList
            bucket={bucket}
            prefix=""
            filter={filter}
            selectedKey={selectedKey}
            autoExpandPrefixes={autoExpandPrefixes}
            onContextObject={(x, y, key, name) =>
              setMenuFor({ x, y, kind: "object", bucket, key, name })
            }
          />
        )}
      </li>
      {menuFor && (
        <S3ObjectMenu
          x={menuFor.x}
          y={menuFor.y}
          bucket={menuFor.bucket}
          k={menuFor.key}
          name={menuFor.name}
          onClose={() => setMenuFor(null)}
        />
      )}
    </ul>
  );
}

// ---------------------- Recursive prefix listing ----------------------

interface S3PrefixListProps {
  bucket: string;
  prefix: string;
  filter: string;
  selectedKey: string | null;
  autoExpandPrefixes: Set<string>;
  onContextObject: (x: number, y: number, key: string, name: string) => void;
}

function S3PrefixList({
  bucket,
  prefix,
  filter,
  selectedKey,
  autoExpandPrefixes,
  onContextObject,
}: S3PrefixListProps) {
  const { data, isLoading, error } = useS3List(bucket, prefix);
  const [openSub, setOpenSub] = useState<Set<string>>(new Set());
  const openTab = useTabStore((s) => s.openTab);

  if (isLoading) return <p className="placeholder tree-child">…</p>;
  if (error) return <p className="tree-error tree-child">S3 一覧失敗</p>;

  const subs = data?.subfolders ?? [];
  const subSet = new Set(subs);
  const objs = (data?.objects ?? []).filter((o) =>
    !isS3FolderMarker(o.key, prefix, subSet),
  );
  const f = filter.toLowerCase();
  const filteredSubs = f
    ? subs.filter((s) => s.toLowerCase().includes(f))
    : subs;
  const filteredObjs = f
    ? objs.filter((o) => o.key.toLowerCase().includes(f))
    : objs;

  const containsSelection =
    selectedKey != null &&
    (selectedKey.startsWith(prefix) ||
      filteredObjs.some((o) => o.key === selectedKey));

  function toggleSub(p: string) {
    setOpenSub((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  }

  function isSubOpen(sp: string): boolean {
    return openSub.has(sp) || autoExpandPrefixes.has(sp);
  }

  function openFilePreview(bucket: string, key: string) {
    const name = key.split("/").pop() || key;
    openTab({
      title: name,
      kind: "file_preview",
      ref: { bucket, key },
      dedupeKey: `file:${bucket}/${key}`,
    });
  }

  return (
    <ul
      className={
        "tree-child-list" +
        (containsSelection ? " tree-child-list--guided" : "")
      }
    >
      {filteredSubs.map((sp) => {
        const label = sp.slice(prefix.length).replace(/\/$/, "");
        const isOpen = isSubOpen(sp);
        const onSelectedPath =
          selectedKey != null &&
          (selectedKey.startsWith(sp) || selectedKey === sp);
        return (
          <li key={sp} className="tree-node">
            <div
              className={
                "tree-row tree-row--schema" +
                (onSelectedPath ? " tree-row--path" : "")
              }
              onClick={() => toggleSub(sp)}
            >
              <span className="tree-caret">
                <IconChevronToggle expanded={isOpen} />
              </span>
              <span className="tree-label" title={sp}>
                {label || sp}
              </span>
            </div>
            {isOpen && (
              <S3PrefixList
                bucket={bucket}
                prefix={sp}
                filter={filter}
                selectedKey={selectedKey}
                autoExpandPrefixes={autoExpandPrefixes}
                onContextObject={onContextObject}
              />
            )}
          </li>
        );
      })}
      {filteredObjs.map((o) => {
        const name = o.key.slice(prefix.length) || o.key;
        const isSelected = selectedKey === o.key;
        return (
          <li
            key={o.key}
            className={
              "tree-row tree-row--table" +
              (isSelected ? " tree-row--selected" : "")
            }
            aria-current={isSelected ? "true" : undefined}
            onClick={() => openFilePreview(bucket, o.key)}
            onContextMenu={(e) => {
              e.preventDefault();
              onContextObject(e.clientX, e.clientY, o.key, name);
            }}
          >
            <FileTypeIcon filename={name} />
            <span className="tree-label" title={o.key}>
              {name}
            </span>
          </li>
        );
      })}
      {filteredSubs.length === 0 && filteredObjs.length === 0 && (
        <li className="placeholder tree-child">(empty)</li>
      )}
    </ul>
  );
}

/** S3 のフォルダマーカー (key が `/` 終端) をファイル一覧から除外する。 */
function isS3FolderMarker(
  key: string,
  prefix: string,
  subfolders: Set<string>,
): boolean {
  const rel = key.slice(prefix.length);
  if (!rel) return true;
  if (rel.endsWith("/")) return true;
  if (subfolders.has(key) || subfolders.has(`${key}/`)) return true;
  return false;
}

// ---------------------- Object right-click menu ----------------------

interface S3ObjectMenuProps {
  x: number;
  y: number;
  bucket: string;
  k: string;
  name: string;
  onClose: () => void;
}

function S3ObjectMenu({ x, y, bucket, k, name, onClose }: S3ObjectMenuProps) {
  const openTab = useTabStore((s) => s.openTab);
  const setPendingPrompt = useChatStore((s) => s.setPendingPrompt);
  return (
    <NodeMenu
      x={x}
      y={y}
      onClose={onClose}
      items={[
        {
          label: `Preview: ${name}`,
          onSelect: () =>
            openTab({
              title: name,
              kind: "file_preview",
              ref: { bucket, key: k },
              dedupeKey: `file:${bucket}/${k}`,
            }),
        },
        {
          label: "このファイルを取り込んで",
          onSelect: () =>
            setPendingPrompt(
              `s3://${bucket}/${k} を取り込んでテーブルを作って`,
            ),
        },
      ]}
    />
  );
}

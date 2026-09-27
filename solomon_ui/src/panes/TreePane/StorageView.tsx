/**
 * ストレージ (S3) ビュー — バケット配下の階層を表示。
 */
import { useS3Buckets } from "../../api/files";
import { S3Tree } from "./S3Tree";

interface StorageViewProps {
  filter: string;
}

export function StorageView({ filter }: StorageViewProps) {
  const { data: buckets = [], isLoading } = useS3Buckets();

  return (
    <div className="explorer-view explorer-view--storage">
      <div className="explorer-section-head">
        <span className="explorer-section-title">Storage</span>
        <span className="explorer-section-count">({buckets.length})</span>
      </div>
      <div className="explorer-storage-body">
        {isLoading && (
          <p className="explorer-placeholder">Loading storage…</p>
        )}
        {!isLoading &&
          buckets.map((b) => (
            <S3Tree key={b} bucket={b} filter={filter} />
          ))}
      </div>
    </div>
  );
}

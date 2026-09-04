import { useEffect, useState } from "react";
import { fetchFormFields } from "../api";
import PageScrollViewer from "./PageScrollViewer";

function fieldKey(field) {
  return `${field.page}:${field.index}`;
}

export default function FormFillCanvas({ fileId, pageCount, onChange }) {
  const [fields, setFields] = useState([]);
  const [values, setValues] = useState({});
  const [initialValues, setInitialValues] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!fileId) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await fetchFormFields(fileId);
        if (cancelled) return;
        const initial = {};
        for (const f of data.fields) {
          initial[fieldKey(f)] = f.value;
        }
        setFields(data.fields);
        setValues(initial);
        setInitialValues(initial);
      } catch (err) {
        if (!cancelled) setError("Could not load form fields: " + err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [fileId]);

  useEffect(() => {
    const changed = fields
      .filter((f) => values[fieldKey(f)] !== initialValues[fieldKey(f)])
      .map((f) => ({ page: f.page, index: f.index, value: values[fieldKey(f)] }));
    onChange(changed);
  }, [values, fields, initialValues]);

  if (!fileId || !pageCount) return null;

  function setFieldValue(field, value) {
    setValues((v) => ({ ...v, [fieldKey(field)]: value }));
  }

  if (loading) {
    return <p className="form-fill-canvas__status">Loading form fields…</p>;
  }

  if (error) {
    return <p className="form-fill-canvas__status form-fill-canvas__status--error">{error}</p>;
  }

  if (fields.length === 0) {
    return <p className="form-fill-canvas__status">No fillable fields found in this document.</p>;
  }

  function renderField(field) {
    const key = fieldKey(field);
    const style = {
      left: `${field.rect.left * 100}%`,
      top: `${field.rect.top * 100}%`,
      width: `${(1 - field.rect.left - field.rect.right) * 100}%`,
      height: `${(1 - field.rect.top - field.rect.bottom) * 100}%`,
    };
    if (field.type === "text") {
      return (
        <input
          key={key}
          type="text"
          className="form-fill-canvas__field"
          style={style}
          value={values[key] ?? ""}
          onChange={(e) => setFieldValue(field, e.target.value)}
          title={field.label}
        />
      );
    }
    if (field.type === "checkbox") {
      return (
        <input
          key={key}
          type="checkbox"
          className="form-fill-canvas__field"
          style={style}
          checked={Boolean(values[key])}
          onChange={(e) => setFieldValue(field, e.target.checked)}
          title={field.label}
        />
      );
    }
    return (
      <select
        key={key}
        className="form-fill-canvas__field"
        style={style}
        value={values[key] ?? ""}
        onChange={(e) => setFieldValue(field, e.target.value)}
        title={field.label}
      >
        <option value="" disabled>
          — Select —
        </option>
        {(field.choices ?? []).map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    );
  }

  return (
    <div className="form-fill-canvas">
      <PageScrollViewer
        fileId={fileId}
        pageCount={pageCount}
        className="form-fill-canvas__viewer"
        renderPageOverlay={(pageNumber) => (
          <div className="form-fill-canvas__stage">
            {fields.filter((f) => f.page === pageNumber).map(renderField)}
          </div>
        )}
      />
    </div>
  );
}

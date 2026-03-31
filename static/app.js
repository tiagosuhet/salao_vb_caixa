document.addEventListener("DOMContentLoaded", () => {
  const flashItems = document.querySelectorAll("[data-autohide]");
  if (flashItems.length > 0) {
    window.setTimeout(() => {
      flashItems.forEach((item) => item.classList.add("is-hidden"));
    }, 4200);
  }

  const categoriesDataNode = document.getElementById("categories-data");
  const categorySelect = document.querySelector("[data-category-select]");
  const typeInputs = document.querySelectorAll("input[name='transaction_type']");

  if (categoriesDataNode && categorySelect && typeInputs.length > 0) {
    const categoriesByType = JSON.parse(categoriesDataNode.textContent);
    const buildOptions = (selectedType, preferredValue) => {
      const items = categoriesByType[selectedType] || [];
      categorySelect.innerHTML = "";

      items.forEach((item, index) => {
        const option = document.createElement("option");
        option.value = String(item.id);
        option.textContent = item.name;

        if (
          (preferredValue && String(item.id) === String(preferredValue)) ||
          (!preferredValue && index === 0)
        ) {
          option.selected = true;
        }

        categorySelect.appendChild(option);
      });
    };

    const currentSelected = categorySelect.dataset.current;
    const selectedTypeInput = Array.from(typeInputs).find((input) => input.checked);
    const initialType = selectedTypeInput ? selectedTypeInput.value : "entrada";
    buildOptions(initialType, currentSelected);

    typeInputs.forEach((input) => {
      input.addEventListener("change", () => {
        buildOptions(input.value, "");
      });
    });
  }

  const deleteForms = document.querySelectorAll("[data-confirm-delete]");
  deleteForms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      const confirmed = window.confirm("Deseja realmente excluir este lancamento?");
      if (!confirmed) {
        event.preventDefault();
      }
    });
  });

  const amountInput = document.querySelector("[data-autofocus-amount]");
  if (amountInput) {
    amountInput.focus();
  }

  const currencyFormatter = new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  });
  const compactFormatter = new Intl.NumberFormat("pt-BR", {
    notation: "compact",
    maximumFractionDigits: 1,
  });
  const svgNS = "http://www.w3.org/2000/svg";

  const formatCurrency = (valueInCents) =>
    currencyFormatter.format((valueInCents || 0) / 100);

  const formatCompactCurrency = (valueInCents) => {
    const value = (valueInCents || 0) / 100;
    if (Math.abs(value) >= 1000) {
      return compactFormatter.format(value);
    }
    return currencyFormatter.format(value);
  };

  const createEmptyChart = (container, message) => {
    container.innerHTML = "";
    const empty = document.createElement("div");
    empty.className = "chart-empty";
    empty.textContent = message;
    container.appendChild(empty);
  };

  const createSvg = (width, height) => {
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("role", "img");
    return svg;
  };

  const appendSvgText = (svg, text, x, y, options = {}) => {
    const node = document.createElementNS(svgNS, "text");
    node.textContent = text;
    node.setAttribute("x", x);
    node.setAttribute("y", y);
    node.setAttribute("fill", options.fill || "rgba(255, 255, 255, 0.72)");
    node.setAttribute("font-size", options.fontSize || "12");
    node.setAttribute("font-weight", options.fontWeight || "700");
    node.setAttribute("text-anchor", options.anchor || "start");
    svg.appendChild(node);
  };

  const renderLineChart = (container, data) => {
    const points = data.points || [];
    const series = data.series || [];
    const maxValue = Math.max(
      0,
      ...points.flatMap((point) => series.map((item) => point[item.key] || 0)),
    );

    if (points.length === 0 || series.length === 0 || maxValue === 0) {
      createEmptyChart(container, "Ainda nao ha volume suficiente para exibir este grafico.");
      return;
    }

    const width = 820;
    const height = 280;
    const padding = { top: 24, right: 24, bottom: 42, left: 58 };
    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;
    const svg = createSvg(width, height);
    container.innerHTML = "";

    [0, 0.5, 1].forEach((ratio) => {
      const y = padding.top + innerHeight - innerHeight * ratio;
      const grid = document.createElementNS(svgNS, "line");
      grid.setAttribute("x1", padding.left);
      grid.setAttribute("x2", width - padding.right);
      grid.setAttribute("y1", y);
      grid.setAttribute("y2", y);
      grid.setAttribute("stroke", "rgba(255, 255, 255, 0.12)");
      grid.setAttribute("stroke-width", "1");
      svg.appendChild(grid);

      appendSvgText(
        svg,
        formatCompactCurrency(maxValue * ratio),
        padding.left - 8,
        y + 4,
        { anchor: "end", fontSize: "11" },
      );
    });

    const xForIndex = (index) => {
      if (points.length === 1) {
        return padding.left + innerWidth / 2;
      }
      return padding.left + (innerWidth * index) / (points.length - 1);
    };

    const yForValue = (value) =>
      padding.top + innerHeight - (innerHeight * value) / maxValue;

    const labelStep = Math.max(1, Math.ceil(points.length / 6));

    points.forEach((point, index) => {
      if (index % labelStep !== 0 && index !== points.length - 1) {
        return;
      }
      appendSvgText(svg, point.label, xForIndex(index), height - 12, {
        anchor: "middle",
        fontSize: "11",
      });
    });

    series.forEach((seriesItem) => {
      const polyline = document.createElementNS(svgNS, "polyline");
      const polylinePoints = points
        .map((point, index) => `${xForIndex(index)},${yForValue(point[seriesItem.key] || 0)}`)
        .join(" ");
      polyline.setAttribute("points", polylinePoints);
      polyline.setAttribute("fill", "none");
      polyline.setAttribute("stroke", seriesItem.color);
      polyline.setAttribute("stroke-width", "4");
      polyline.setAttribute("stroke-linecap", "round");
      polyline.setAttribute("stroke-linejoin", "round");
      svg.appendChild(polyline);

      const lastPoint = points[points.length - 1];
      const circle = document.createElementNS(svgNS, "circle");
      circle.setAttribute("cx", xForIndex(points.length - 1));
      circle.setAttribute("cy", yForValue(lastPoint[seriesItem.key] || 0));
      circle.setAttribute("r", "5");
      circle.setAttribute("fill", seriesItem.color);
      svg.appendChild(circle);
    });

    container.appendChild(svg);
  };

  const polarToCartesian = (centerX, centerY, radius, angleInDegrees) => {
    const angleInRadians = ((angleInDegrees - 90) * Math.PI) / 180.0;
    return {
      x: centerX + radius * Math.cos(angleInRadians),
      y: centerY + radius * Math.sin(angleInRadians),
    };
  };

  const describeArc = (centerX, centerY, radius, startAngle, endAngle) => {
    const start = polarToCartesian(centerX, centerY, radius, endAngle);
    const end = polarToCartesian(centerX, centerY, radius, startAngle);
    const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";

    return [
      "M",
      start.x,
      start.y,
      "A",
      radius,
      radius,
      0,
      largeArcFlag,
      0,
      end.x,
      end.y,
    ].join(" ");
  };

  const renderDonutChart = (container, data) => {
    const labelKey = data.label_key;
    const valueKey = data.value_key;
    const items = (data.items || []).filter((item) => (item[valueKey] || 0) > 0);
    const total = items.reduce((sum, item) => sum + (item[valueKey] || 0), 0);

    if (items.length === 0 || total === 0) {
      createEmptyChart(container, "Sem movimentacao suficiente para montar o mix deste periodo.");
      return;
    }

    const width = 360;
    const height = 240;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = 78;
    const strokeWidth = 28;
    const svg = createSvg(width, height);
    container.innerHTML = "";

    const baseRing = document.createElementNS(svgNS, "circle");
    baseRing.setAttribute("cx", centerX);
    baseRing.setAttribute("cy", centerY);
    baseRing.setAttribute("r", radius);
    baseRing.setAttribute("fill", "none");
    baseRing.setAttribute("stroke", "rgba(255, 255, 255, 0.1)");
    baseRing.setAttribute("stroke-width", strokeWidth);
    svg.appendChild(baseRing);

    let currentAngle = 0;
    items.forEach((item, index) => {
      const sliceValue = item[valueKey] || 0;
      const sliceAngle = (sliceValue / total) * 360;
      const color = (data.colors || [])[index % (data.colors || []).length] || "#ff1fae";

      if (sliceAngle >= 360) {
        const fullCircle = document.createElementNS(svgNS, "circle");
        fullCircle.setAttribute("cx", centerX);
        fullCircle.setAttribute("cy", centerY);
        fullCircle.setAttribute("r", radius);
        fullCircle.setAttribute("fill", "none");
        fullCircle.setAttribute("stroke", color);
        fullCircle.setAttribute("stroke-width", strokeWidth);
        svg.appendChild(fullCircle);
      } else {
        const path = document.createElementNS(svgNS, "path");
        path.setAttribute(
          "d",
          describeArc(centerX, centerY, radius, currentAngle, currentAngle + sliceAngle),
        );
        path.setAttribute("fill", "none");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", strokeWidth);
        path.setAttribute("stroke-linecap", "round");
        svg.appendChild(path);
      }

      currentAngle += sliceAngle;
    });

    appendSvgText(svg, "Total", centerX, centerY - 6, {
      anchor: "middle",
      fontSize: "14",
    });
    appendSvgText(svg, formatCurrency(total), centerX, centerY + 20, {
      anchor: "middle",
      fill: "#ffffff",
      fontSize: "18",
      fontWeight: "800",
    });

    container.appendChild(svg);
  };

  const renderBarChart = (container, data) => {
    const labelKey = data.label_key;
    const valueKey = data.value_key;
    const items = (data.items || []).filter((item) => (item[valueKey] || 0) > 0);

    if (items.length === 0) {
      createEmptyChart(container, "Sem categorias com volume suficiente para este recorte.");
      return;
    }

    const maxValue = Math.max(...items.map((item) => item[valueKey] || 0));
    const wrapper = document.createElement("div");
    wrapper.className = "bar-chart";

    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "bar-row";

      const head = document.createElement("div");
      head.className = "bar-head";

      const label = document.createElement("span");
      label.className = "bar-label";
      label.textContent = item[labelKey];

      const value = document.createElement("span");
      value.className = "bar-value";
      value.textContent = formatCurrency(item[valueKey] || 0);

      head.appendChild(label);
      head.appendChild(value);

      const track = document.createElement("div");
      track.className = "bar-track";

      const fill = document.createElement("div");
      fill.className = "bar-fill";
      fill.style.setProperty("--bar-color", data.color || "#ff1fae");
      fill.style.width = `${((item[valueKey] || 0) / maxValue) * 100}%`;

      track.appendChild(fill);
      row.appendChild(head);
      row.appendChild(track);
      wrapper.appendChild(row);
    });

    container.innerHTML = "";
    container.appendChild(wrapper);
  };

  const renderGroupedBarChart = (container, data) => {
    const labelKey = data.label_key;
    const series = data.series || [];
    const items = (data.items || []).filter((item) =>
      series.some((seriesItem) => (item[seriesItem.key] || 0) > 0),
    );

    if (items.length === 0 || series.length === 0) {
      createEmptyChart(container, "Sem comparativo suficiente para este periodo.");
      return;
    }

    const maxValue = Math.max(
      ...items.flatMap((item) => series.map((seriesItem) => item[seriesItem.key] || 0)),
    );
    const wrapper = document.createElement("div");
    wrapper.className = "bar-chart";

    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "bar-row";

      const label = document.createElement("span");
      label.className = "bar-label";
      label.textContent = item[labelKey];
      row.appendChild(label);

      const groupBars = document.createElement("div");
      groupBars.className = "group-bars";

      series.forEach((seriesItem) => {
        const seriesValue = item[seriesItem.key] || 0;

        const meta = document.createElement("div");
        meta.className = "group-meta";

        const metaLabel = document.createElement("span");
        metaLabel.textContent = seriesItem.label;

        const metaValue = document.createElement("span");
        metaValue.textContent = formatCurrency(seriesValue);

        meta.appendChild(metaLabel);
        meta.appendChild(metaValue);

        const track = document.createElement("div");
        track.className = "group-track";

        const fill = document.createElement("div");
        fill.className = "group-fill";
        fill.style.setProperty("--bar-color", seriesItem.color);
        fill.style.width = `${(seriesValue / maxValue) * 100}%`;

        track.appendChild(fill);
        groupBars.appendChild(meta);
        groupBars.appendChild(track);
      });

      row.appendChild(groupBars);
      wrapper.appendChild(row);
    });

    container.innerHTML = "";
    container.appendChild(wrapper);
  };

  const chartRenderers = {
    line: renderLineChart,
    donut: renderDonutChart,
    bar: renderBarChart,
    "grouped-bar": renderGroupedBarChart,
  };

  const chartNodes = document.querySelectorAll("[data-bi-chart]");
  chartNodes.forEach((container) => {
    const chartType = container.dataset.biChart;
    const sourceId = container.dataset.source;
    const sourceNode = document.getElementById(sourceId);

    if (!sourceNode || !chartRenderers[chartType]) {
      return;
    }

    try {
      const chartData = JSON.parse(sourceNode.textContent);
      chartRenderers[chartType](container, chartData);
    } catch (error) {
      createEmptyChart(container, "Nao foi possivel carregar este grafico agora.");
    }
  });
});

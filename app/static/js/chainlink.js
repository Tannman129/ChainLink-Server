import { csrf, currentUser, session } from "./auth.js";

const view = document.querySelector("#view");
const pageSize = 12;
let requestController;
let initialNavigation = true;
const courseDialog = document.querySelector("#course-dialog");
const courseForm = document.querySelector("#course-form");
const courseMessage = document.querySelector("#course-message");
const courseSave = document.querySelector("#course-save");
const courseCancel = document.querySelector("#course-cancel");
const courseSignIn = document.querySelector("#course-sign-in");
const courseFeedback = document.querySelector("#course-feedback");
let savingCourse = false;
let createdCourseHash;

function updateCourseAccess() {
  const administrator = currentUser?.role === "administrator";
  const add = document.querySelector("#add-course");
  if (add) add.hidden = !administrator;
  courseSave.disabled = savingCourse || !administrator;
  courseSignIn.hidden = administrator || !courseDialog.open;
}
window.addEventListener("chainlink-session-changed", updateCourseAccess);

function addCourse() {
  if (currentUser?.role !== "administrator") return;
  courseMessage.textContent = "";
  courseDialog.showModal();
}
courseCancel.addEventListener("click", () => courseDialog.close());
courseSignIn.addEventListener("click", () => document.querySelector("#sign-in").click());
courseDialog.addEventListener("cancel", event => {
  if (savingCourse) event.preventDefault();
});
courseDialog.addEventListener("close", () => {
  courseForm.reset();
  courseForm.elements.name.setCustomValidity("");
  courseMessage.textContent = "";
  updateCourseAccess();
});
courseForm.elements.name.addEventListener("input", () => {
  courseForm.elements.name.setCustomValidity("");
});
courseForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (savingCourse || currentUser?.role !== "administrator") return;
  const name = courseForm.elements.name;
  name.setCustomValidity(name.value.trim() ? "" : "Enter a course name.");
  if (!courseForm.reportValidity()) return;
  const payload = { name: name.value.trim(), description: courseForm.elements.description.value || null };
  savingCourse = true;
  updateCourseAccess();
  courseCancel.disabled = true;
  name.disabled = true;
  courseForm.elements.description.disabled = true;
  courseForm.setAttribute("aria-busy", "true");
  courseMessage.textContent = "Saving course…";
  try {
    const response = await fetch("/v1/courses", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) {
        await session();
        throw new Error(currentUser?.role === "administrator"
          ? "Your security token was refreshed. Your entries are preserved; select Save to try again."
          : "Administrator sign-in is required to save a course. Your entries have been preserved.");
      }
      throw new Error(response.status === 422
        ? "Check the course name (1–200 characters) and description (up to 10,000 characters). Your entries have been preserved."
        : "The server could not save the course. Your entries have been preserved; please try again.");
    }
    const course = await response.json();
    courseDialog.close();
    createdCourseHash = `#courses/${encodeURIComponent(course.id)}`;
    courseFeedback.textContent = `Course “${course.name}” created successfully.`;
    courseFeedback.hidden = false;
    location.hash = createdCourseHash;
  } catch (error) {
    courseMessage.textContent = error instanceof TypeError || error.name === "TimeoutError"
      ? "Couldn’t confirm whether the course was saved. Your entries are preserved. Check the course list before trying again."
      : error.message;
  } finally {
    savingCourse = false;
    courseCancel.disabled = false;
    name.disabled = false;
    courseForm.elements.description.disabled = false;
    courseForm.setAttribute("aria-busy", "false");
    updateCourseAccess();
  }
});

// Catalog data is assigned only through textContent, never interpreted as HTML.
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
function link(text, href, className = "") {
  const node = element("a", className, text);
  node.href = href;
  return node;
}
function button(text, action, className = "button") {
  const node = element("button", className, text);
  node.type = "button";
  node.addEventListener("click", action);
  return node;
}
function state(target, title, description, retry, loading = false) {
  const box = element("div", "state");
  if (loading) {
    const spinner = element("span", "loading-mark");
    spinner.setAttribute("aria-hidden", "true");
    box.append(spinner);
  }
  box.append(element("h2", "", title), element("p", "", description));
  if (retry) box.append(button("Try again", retry));
  target.replaceChildren(box);
}
async function getJSON(url, signal) {
  const response = await fetch(url, {
    signal: AbortSignal.any([signal, AbortSignal.timeout(12000)]),
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    const error = new Error(
      response.status === 404
        ? "This course could not be found."
        : "The server could not complete this request.",
    );
    error.status = response.status;
    throw error;
  }
  return response.json();
}
function sectionHeading(title, description) {
  const heading = element("div", "section-heading");
  heading.append(element("h2", "", title));
  if (description) heading.append(element("span", "", description));
  return heading;
}

function icon(name) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  node.classList.add("icon");
  node.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `/static/icons.svg#${name}`);
  node.append(use);
  return node;
}

function dashboard(signal) {
  function metric(label, iconName, note) {
    const card = element("section", "panel metric-card");
    const top = element("div", "metric-label");
    top.append(element("h2", "", label), icon(iconName));
    const value = element("p", "metric-value", "—");
    const detail = element("p", "metric-note", note);
    card.append(top, value, detail);
    return { card, value, detail };
  }
  const libraryMetric = metric(
    "Course library",
    "courses",
    "Loading the catalog…",
  );
  libraryMetric.value.id = "catalog-count";
  const layoutMetric = metric(
    "Available layouts",
    "layouts",
    "Choose a course below",
  );
  layoutMetric.value.id = "layout-count";
  const status = element("section", "panel metric-card connection-card");
  const statusTitle = element("div", "metric-label");
  statusTitle.append(element("h2", "", "API connection"), icon("server"));
  const indicator = element("p", "status-indicator");
  indicator.setAttribute("role", "status");
  const healthNote = element(
    "p",
    "metric-note",
    "Process reachability only · Database not checked",
  );
  const healthActions = element("div", "health-actions");
  const version = element("span", "version", "Version unavailable");
  const check = button("Check again", checkHealth, "text-button");
  healthActions.append(version, check);
  status.append(statusTitle, indicator, healthNote, healthActions);
  const metrics = element("div", "metrics-grid");
  metrics.append(libraryMetric.card, layoutMetric.card, status);

  const library = element("section", "panel library-panel");
  const libraryHead = element("div", "panel-heading");
  const libraryTitle = element("div");
  libraryTitle.append(
    element("p", "eyebrow", "THE COURSE CATALOG"),
    element("h2", "", "Your fairways"),
  );
  libraryHead.append(
    libraryTitle,
    link("View all courses ↗", "#courses", "text-link"),
  );
  const courseList = element("div", "dashboard-course-list");
  const libraryFoot = element("div", "panel-foot");
  libraryFoot.append(
    icon("lock"),
    element(
      "span",
      "",
      "Administrators can add courses from the Courses page. Layout editing is not available yet.",
    ),
  );
  library.append(libraryHead, courseList, libraryFoot);

  const overview = element("section", "panel overview-panel");
  const overviewHead = element("div", "panel-heading");
  overviewHead.append(element("h2", "", "Course at a glance"), icon("basket"));
  const picker = element("div", "course-picker");
  const label = element("label", "", "Selected course");
  label.htmlFor = "dashboard-course";
  const select = element("select");
  select.id = "dashboard-course";
  select.disabled = true;
  picker.append(label, select);
  const graphView = element("div", "dashboard-layouts");
  const branding = element("div", "brand-artwork");
  const artwork = element("img");
  artwork.src = "/static/images/chainlink-basket.webp";
  artwork.srcset =
    "/static/images/chainlink-basket-small.webp 240w, /static/images/chainlink-basket.webp 480w";
  artwork.sizes = "96px";
  artwork.width = 480;
  artwork.height = 587;
  artwork.alt = "ChainLink Midnight Red disc golf basket artwork";
  artwork.decoding = "async";
  const brandCopy = element("div");
  brandCopy.append(
    element("p", "eyebrow", "CHAINLINK"),
    element("h3", "", "Your game. Your server."),
    element("p", "", "Disc golf, on your terms."),
  );
  branding.append(artwork, brandCopy);
  overview.append(overviewHead, picker, graphView, branding);
  const columns = element("div", "dashboard-columns");
  columns.append(library, overview);
  const roadmap = element("section", "panel roadmap");
  const roadmapTitle = element("div", "roadmap-title");
  roadmapTitle.append(
    element("h2", "", "Room for the rest of your game"),
    element("p", "", "Planned features · Not available yet"),
  );
  const future = element("ul", "roadmap-items");
  for (const [name, symbol] of [
    ["Players", "players"],
    ["Android sync", "sync"],
  ]) {
    const item = element("li");
    item.append(
      icon(symbol),
      element("span", "", name),
      element("span", "badge muted", "PLANNED"),
    );
    future.append(item);
  }
  roadmapTitle.append(link("View Round History →", "#rounds", "text-link"), link("Personal statistics →", "#statistics", "text-link"));
  roadmap.append(roadmapTitle, future);
  view.replaceChildren(metrics, columns, roadmap);

  let graphController;
  async function loadGraph() {
    graphController?.abort();
    graphController = new AbortController();
    const graphSignal = AbortSignal.any([signal, graphController.signal]);
    layoutMetric.value.textContent = "—";
    layoutMetric.detail.textContent = "Loading selected course…";
    graphView.setAttribute("aria-busy", "true");
    state(
      graphView,
      "Loading layouts…",
      "Reading stored course configurations.",
      null,
      true,
    );
    try {
      const course = await getJSON(
        `/v1/courses/${encodeURIComponent(select.value)}/graph`,
        graphSignal,
      );
      if (graphSignal.aborted) return;
      layoutMetric.value.textContent = course.layouts.length;
      layoutMetric.detail.textContent = `In ${course.name}`;
      const description = element(
        "p",
        "overview-description",
        course.description || "No description has been added to this course.",
      );
      const list = element("div", "layout-preview-list");
      for (const layout of course.layouts) {
        const entry = link(
          "",
          `#layouts/${encodeURIComponent(course.id)}?layout=${encodeURIComponent(layout.id)}`,
          "layout-preview",
        );
        const info = element("div");
        const defaultPars = layout.holes.map(
          (hole) =>
            hole.configurations.find(
              (config) => config.id === hole.default?.configuration_id,
            )?.par,
        );
        const par =
          layout.holes.length && defaultPars.every((value) => value != null)
            ? ` · Default par ${defaultPars.reduce((sum, value) => sum + value, 0)}`
            : " · Defaults incomplete";
        info.append(
          element("h3", "", layout.name),
          element(
            "p",
            "",
            `${layout.holes.length} ${layout.holes.length === 1 ? "hole" : "holes"}${par}`,
          ),
        );
        entry.append(icon("layouts"), info, icon("arrow"));
        list.append(entry);
      }
      if (!course.layouts.length)
        state(
          list,
          "No layouts yet",
          "This course has no stored playable layouts.",
        );
      graphView.replaceChildren(
        description,
        list,
        link(
          "Open course guide →",
          `#courses/${encodeURIComponent(course.id)}`,
          "text-link",
        ),
      );
    } catch (error) {
      if (graphSignal.aborted) return;
      layoutMetric.detail.textContent = "Selected course unavailable";
      state(
        graphView,
        "Couldn’t load layouts.",
        "The API or database may be unavailable.",
        loadGraph,
      );
    } finally {
      if (!graphSignal.aborted) graphView.setAttribute("aria-busy", "false");
    }
  }
  select.addEventListener("change", loadGraph);
  async function loadLibrary() {
    courseList.setAttribute("aria-busy", "true");
    state(
      courseList,
      "Loading courses…",
      "Reading your local course library.",
      null,
      true,
    );
    try {
      const rows = await getJSON(
        `/v1/courses?limit=${pageSize + 1}&offset=0`,
        signal,
      );
      if (signal.aborted) return;
      const courses = rows.slice(0, pageSize);
      libraryMetric.value.textContent =
        rows.length > pageSize ? `${pageSize}+` : courses.length;
      libraryMetric.detail.textContent =
        rows.length > pageSize
          ? "More courses available · Browse the catalog"
          : "Courses stored in the catalog";
      select.replaceChildren();
      for (const course of courses) {
        const option = element("option", "", course.name);
        option.value = course.id;
        select.append(option);
      }
      select.disabled = !courses.length;
      const entries = courses.slice(0, 5).map((course) => {
        const entry = link(
          "",
          `#courses/${encodeURIComponent(course.id)}`,
          "dashboard-course",
        );
        const mark = element("span", "course-symbol");
        mark.append(icon("courses"));
        const info = element("div", "course-row-copy");
        info.append(
          element("h3", "", course.name),
          element(
            "p",
            "",
            course.description || "Explore layouts, tees, and baskets.",
          ),
        );
        entry.append(mark, info, icon("arrow"));
        return entry;
      });
      courseList.replaceChildren(...entries);
      if (courses.length) {
        const scope = element(
          "p",
          "preview-scope",
          `Showing ${entries.length} of ${courses.length}${rows.length > pageSize ? "+" : ""} courses. Layouts are scoped to the selected course.`,
        );
        courseList.append(scope);
        picker.hidden = false;
        await loadGraph();
      } else {
        picker.hidden = true;
        layoutMetric.detail.textContent = "No course selected";
        state(
          courseList,
          "Your catalog starts here.",
          "No courses are stored yet. Administrators can add a course from the Courses page.",
        );
        state(
          graphView,
          "No course selected",
          "Course layouts will appear here when your catalog has a course.",
        );
      }
    } catch (error) {
      if (signal.aborted) return;
      libraryMetric.value.textContent = "—";
      libraryMetric.detail.textContent = "Catalog unavailable";
      picker.hidden = true;
      state(
        courseList,
        "Couldn’t load the catalog.",
        "Check your connection and try again.",
        loadLibrary,
      );
      state(
        graphView,
        "Waiting for the catalog",
        "Retry the course library to choose a course.",
      );
    } finally {
      if (!signal.aborted) courseList.setAttribute("aria-busy", "false");
    }
  }
  async function checkHealth() {
    check.disabled = true;
    indicator.className = "status-indicator";
    indicator.textContent = "Checking API…";
    try {
      const data = await getJSON(
        "/health",
        AbortSignal.any([signal, AbortSignal.timeout(8000)]),
      );
      if (signal.aborted) return;
      if (data.status !== "ok") throw new Error("Unexpected health response");
      indicator.textContent = "● API reachable";
      indicator.classList.add("reachable");
      version.textContent = data.version
        ? `Server v${data.version}`
        : "Version not reported";
    } catch (error) {
      if (signal.aborted) return;
      indicator.textContent = "○ API unreachable";
      indicator.classList.add("unreachable");
      version.textContent = "Version unavailable";
    } finally {
      check.disabled = false;
    }
  }
  checkHealth();
  loadLibrary();
}

async function catalog(section, page, signal) {
  state(
    view,
    "Loading courses…",
    "Getting the course library from your server.",
    null,
    true,
  );
  // One extra row determines whether another page exists without inventing a total.
  const courses = await getJSON(
    `/v1/courses?limit=${pageSize + 1}&offset=${(page - 1) * pageSize}`,
    signal,
  );
  const toolbar = element("div", "toolbar");
  toolbar.append(
    element(
      "span",
      "",
      section === "layouts"
        ? "Choose a course to explore its layouts."
        : "Your local course library. Ready to explore.",
    ),
  );
  const refresh = button("Refresh", navigate);
  const actions = element("div", "account-controls");
  actions.append(refresh);
  if (section === "courses") {
    const add = button("Add Course", addCourse, "button primary");
    add.id = "add-course";
    add.hidden = currentUser?.role !== "administrator";
    actions.append(add);
  }
  toolbar.append(actions);
  const content = element("div", "course-grid");
  const visible = courses.slice(0, pageSize);
  for (const course of visible) {
    const card = element("article", "course-card");
    const art = element("div", "course-art");
    art.setAttribute("aria-hidden", "true");
    art.append(icon("courses"), element("span", "", "COURSE GUIDE"));
    const body = element("div", "course-body");
    body.append(
      element("h2", "", course.name),
      element(
        "p",
        "",
        course.description ||
          "A new fairway to explore. No description has been added.",
      ),
      link(
        section === "layouts"
          ? "Explore layouts  →"
          : "View course & layouts  →",
        `#${section}/${encodeURIComponent(course.id)}`,
      ),
    );
    card.append(art, body);
    content.append(card);
  }
  if (!visible.length)
    state(
      content,
      page === 1 ? "The fairway is wide open." : "No courses on this page.",
      page === 1
        ? "There are no courses in this catalog yet. An administrator can add a course from the Courses page."
        : "Return to the previous page to keep exploring.",
    );
  const pagination = element("nav", "pagination");
  pagination.setAttribute("aria-label", "Course pages");
  pagination.append(
    element(
      "span",
      "",
      `Page ${page} · ${visible.length} ${visible.length === 1 ? "course" : "courses"} shown`,
    ),
  );
  const controls = element("div");
  const previous = button("← Previous", () => {
    location.hash = `${section}?page=${page - 1}`;
  });
  previous.disabled = page <= 1;
  const next = button("Next →", () => {
    location.hash = `${section}?page=${page + 1}`;
  });
  next.disabled = courses.length <= pageSize;
  controls.append(previous, next);
  pagination.append(controls);
  view.replaceChildren(toolbar, content, pagination);
}

function layoutCard(layout, index, selectedLayoutId) {
  const card = element("details", "panel layout-card");
  card.open = selectedLayoutId ? layout.id === selectedLayoutId : index === 0;
  const summary = element("summary", "", layout.name);
  summary.append(
    element(
      "small",
      "",
      `${layout.holes.length} ${layout.holes.length === 1 ? "hole" : "holes"} · Stored playable configurations`,
    ),
  );
  const content = element("div", "layout-content");
  if (!layout.holes.length)
    content.append(element("p", "", "No holes are stored for this layout."));
  for (const hole of layout.holes) {
    content.append(element("h3", "hole-heading", `Hole ${hole.number}`));
    const wrap = element("div", "table-wrap");
    // Named, focusable scroll region makes wide tables usable with a keyboard.
    wrap.tabIndex = 0;
    wrap.setAttribute("role", "region");
    wrap.setAttribute(
      "aria-label",
      `Hole ${hole.number} playable configurations`,
    );
    const table = element("table");
    const caption = element(
      "caption",
      "sr-only",
      `Hole ${hole.number} playable configurations`,
    );
    const head = element("thead");
    const row = element("tr");
    for (const title of ["Tee", "Basket", "Par", "Distance", "Default"]) {
      const cell = element("th", "", title);
      cell.scope = "col";
      row.append(cell);
    }
    head.append(row);
    const body = element("tbody");
    const tees = new Map(hole.tees.map((tee) => [tee.id, tee.name]));
    const baskets = new Map(
      hole.baskets.map((basket) => [basket.id, basket.name]),
    );
    for (const configuration of hole.configurations) {
      const row = element("tr");
      for (const value of [
        tees.get(configuration.tee_id) ?? "Unknown tee",
        baskets.get(configuration.basket_id) ?? "Unknown basket",
        configuration.par,
        configuration.distance_ft == null
          ? "Not recorded"
          : `${configuration.distance_ft} ft`,
      ])
        row.append(element("td", "", value));
      row.append(
        element(
          "td",
          "default-label",
          hole.default?.configuration_id === configuration.id ? "Default" : "—",
        ),
      );
      body.append(row);
    }
    table.append(caption, head, body);
    wrap.append(table);
    content.append(wrap);
    if (!hole.configurations.length)
      content.append(
        element(
          "p",
          "",
          "No playable configurations are stored for this hole.",
        ),
      );
  }
  card.append(summary, content);
  return card;
}

async function courseDetail(section, id, signal, selectedLayoutId) {
  state(
    view,
    "Loading course…",
    "Finding its layouts, tees, and baskets.",
    null,
    true,
  );
  const course = await getJSON(
    `/v1/courses/${encodeURIComponent(id)}/graph`,
    signal,
  );
  const back = link(
    section === "layouts" ? "← Choose another course" : "← Back to courses",
    `#${section}`,
    "back-link",
  );
  const header = element("section", "panel detail-header");
  header.append(
    element("p", "eyebrow", "COURSE GUIDE"),
    element("h2", "", course.name),
    element(
      "p",
      "course-description",
      course.description || "No course description has been added.",
    ),
  );
  const layouts = element("div");
  const selected = course.layouts.some(
    (layout) => layout.id === selectedLayoutId,
  )
    ? selectedLayoutId
    : null;
  course.layouts.forEach((layout, index) =>
    layouts.append(layoutCard(layout, index, selected)),
  );
  if (!course.layouts.length)
    state(
      layouts,
      "A course with room to grow.",
      "No layouts are stored for this course yet.",
    );
  view.replaceChildren(
    back,
    header,
    sectionHeading(
      "Available layouts",
      `${course.layouts.length} ${course.layouts.length === 1 ? "layout" : "layouts"}`,
    ),
    layouts,
  );
}

function relativeScore(value) {
  return value === 0 ? "E" : value > 0 ? `+${value}` : String(value);
}
function playedDate(value) {
  return new Date(value).toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}
function roundSignIn(section = "Round History") {
  document.querySelector("#account-name").textContent = "";
  document.querySelector("#sign-in").hidden = false;
  document.querySelector("#sign-out").hidden = true;
  state(view, `Sign in to view ${section}`, "Your completed rounds and statistics are private. Sign in to continue.");
  view.firstChild.append(button("Sign in", () => document.querySelector("#sign-in").click(), "button primary"));
}
async function roundHistory(id, page, signal) {
  state(view, id ? "Loading scorecard…" : "Loading rounds…", "Reading your private round history.", null, true);
  try {
    const data = await getJSON(id
      ? `/v1/rounds/${encodeURIComponent(id)}`
      : `/v1/rounds?limit=${pageSize + 1}&offset=${(page - 1) * pageSize}`, signal);
    if (signal.aborted) return;
    if (id) {
      roundScorecard(data, page);
      return;
    }
    const toolbar = element("div", "toolbar");
    toolbar.append(element("span", "", "Completed rounds · Only visible to your account"), button("Refresh", navigate));
    const list = element("div", "round-list");
    for (const round of data.slice(0, pageSize)) {
      const card = element("article", "panel round-card");
      const date = element("time", "round-date", playedDate(round.completed_at));
      date.dateTime = round.completed_at;
      const heading = element("h2");
      heading.append(link(round.course_name, `#rounds/${encodeURIComponent(round.id)}?page=${page}`));
      card.append(date, heading, element("p", "round-meta", `${round.layout_name} · ${round.holes.length} holes · Par ${round.total_par}`));
      const players = element("ul", "round-results");
      for (const participant of round.participants) {
        const item = element("li");
        item.append(element("span", "", participant.name), element("strong", "", `${participant.total_strokes} strokes (${relativeScore(participant.score_to_par)})`));
        players.append(item);
      }
      card.append(players, link("View scorecard →", `#rounds/${encodeURIComponent(round.id)}?page=${page}`, "text-link"));
      list.append(card);
    }
    if (!data.length) state(list, page === 1 ? "No rounds yet" : "No rounds on this page", page === 1
      ? "Completed rounds stored in your account will appear here."
      : "Return to the previous page to browse your history.");
    const pagination = element("nav", "pagination");
    pagination.setAttribute("aria-label", "Round history pages");
    pagination.append(element("span", "", `Page ${page} · ${Math.min(data.length, pageSize)} rounds shown`));
    const controls = element("div");
    const previous = button("← Previous", () => { location.hash = `rounds?page=${page - 1}`; });
    previous.disabled = page <= 1;
    const next = button("Next →", () => { location.hash = `rounds?page=${page + 1}`; });
    next.disabled = data.length <= pageSize;
    controls.append(previous, next);
    pagination.append(controls);
    view.replaceChildren(toolbar, list, pagination);
  } catch (error) {
    if (signal.aborted) return;
    if (error.status === 401) roundSignIn();
    else state(view, error.status === 404 ? "Round not found" : "Couldn’t load round history.",
      error.status === 404 ? "This round is unavailable to your account." : "Check your connection and try again.", navigate);
  }
}
function scoringResult(delta) {
  if (delta <= -3) return ["under", `${Math.abs(delta)} under par`];
  if (delta === -2) return ["under", "Eagle"];
  if (delta === -1) return ["under", "Birdie"];
  if (delta === 0) return ["even", "Par"];
  if (delta === 1) return ["over", "Bogey"];
  if (delta === 2) return ["over", "Double bogey"];
  return ["over", `${delta} over par`];
}
function roundScorecard(round, page) {
  const header = element("section", "panel round-card");
  const date = element("time", "round-date", playedDate(round.completed_at));
  date.dateTime = round.completed_at;
  header.append(link("← Round History", `#rounds?page=${page}`, "text-link"), element("h2", "", round.course_name), date,
    element("p", "round-meta", `${round.layout_name} · ${round.holes.length} holes · Par ${round.total_par}`));
  const legend = element("p", "score-legend", "Hole results: ");
  for (const [kind, label] of [["under", "Birdie or better"], ["even", "Par"], ["over", "Bogey or more"]]) {
    legend.append(element("span", `score-result score-${kind}`, label));
  }
  const hint = element("p", "round-meta", "Scroll the scorecard horizontally to see all players. E means even par.");
  const wrap = element("div", "table-wrap scorecard-wrap");
  wrap.tabIndex = 0;
  wrap.setAttribute("role", "region");
  wrap.setAttribute("aria-label", "Round scorecard, scroll for all players");
  const table = element("table", "scorecard");
  table.append(element("caption", "sr-only", `Scorecard for ${round.course_name}, ${round.layout_name}`));
  const head = element("thead");
  const top = element("tr");
  for (const title of ["Hole", "Par", ...round.participants.map(p => p.name)]) {
    const th = element("th", "", title);
    th.scope = "col";
    top.append(th);
  }
  head.append(top);
  const body = element("tbody");
  const scores = round.participants.map(p => new Map(p.scores.map(s => [s.hole_number, s.strokes])));
  for (const hole of round.holes) {
    const row = element("tr");
    const number = element("th", "", hole.number);
    number.scope = "row";
    row.append(number, element("td", "", hole.par));
    round.participants.forEach((participant, index) => {
      const strokes = scores[index].get(hole.number);
      const [kind, label] = scoringResult(strokes - hole.par);
      const cell = element("td");
      const result = element("span", `score-result score-${kind}`, strokes);
      result.title = label;
      result.setAttribute("aria-label", `${participant.name}, hole ${hole.number}: ${strokes} strokes, ${label}`);
      cell.append(result, element("small", "score-detail", label));
      row.append(cell);
    });
    body.append(row);
  }
  const foot = element("tfoot");
  for (const [label, par, values] of [
    ["Total", round.total_par, round.participants.map(p => p.total_strokes)],
    ["To par", "—", round.participants.map(p => relativeScore(p.score_to_par))],
  ]) {
    const row = element("tr");
    const th = element("th", "", label);
    th.scope = "row";
    row.append(th, element("td", "", par), ...values.map(value => element("td", "", value)));
    foot.append(row);
  }
  table.append(head, body, foot);
  wrap.append(table);
  view.replaceChildren(header, legend, hint, wrap);
}

function statisticsTable(caption, headings, rows) {
  const wrap = element("div", "table-wrap statistics-table");
  wrap.tabIndex = 0;
  wrap.setAttribute("role", "region");
  wrap.setAttribute("aria-label", caption);
  const table = element("table");
  table.append(element("caption", "sr-only", caption));
  const head = element("thead");
  const tr = element("tr");
  for (const heading of headings) {
    const th = element("th", "", heading);
    th.scope = "col";
    tr.append(th);
  }
  head.append(tr);
  const body = element("tbody");
  for (const values of rows) {
    const row = element("tr");
    for (const value of values) row.append(element("td", "", value));
    body.append(row);
  }
  table.append(head, body);
  wrap.append(table);
  return wrap;
}
async function statistics(signal) {
  state(view, "Loading statistics…", "Reading your linked scorecards.", null, true);
  try {
    const data = await getJSON("/v1/statistics", signal);
    if (signal.aborted) return;
    const toolbar = element("div", "toolbar");
    toolbar.append(element("span", "", "Only scorecards explicitly linked to your account are included."), button("Refresh", navigate));
    const content = element("div", "statistics-content");
    view.replaceChildren(toolbar, content);
    if (data.excluded_rounds) content.append(element("p", "statistics-notice", `${data.excluded_rounds} incomplete or invalid linked scorecard(s) excluded from all calculations.`));
    if (!data.total_rounds) {
      const empty = element("div");
      state(empty, "No linked rounds yet", "Statistics appear when a completed scorecard explicitly identifies your account. Guest and legacy scorecards are not assigned automatically.");
      content.append(empty);
      return;
    }
    const cards = element("div", "statistics-summary");
    for (const [title, value] of [["Rounds played", data.total_rounds], ["Holes played", data.total_holes]]) {
      const card = element("section", "panel metric-card");
      card.append(element("h2", "metric-label", title), element("p", "metric-value", value));
      cards.append(card);
    }
    content.append(cards);
    const averages = element("section", "panel statistics-panel");
    averages.append(sectionHeading("Round averages", "Separated by hole count; course difficulty can still vary."));
    averages.append(statisticsTable("Averages by round length", ["Length", "Rounds", "Avg strokes / round", "Avg to par / round"], data.by_length.map(r => [`${r.hole_count} holes`, r.rounds, r.average_strokes.toFixed(2), relativeScore(Number(r.average_score_to_par.toFixed(2)))])));
    content.append(averages);
    const scoring = element("section", "panel statistics-panel");
    scoring.append(sectionHeading("Hole scoring", "Percent of all valid holes played · Worse means double bogey or more."));
    const labels = {eagle_or_better: "Eagle or better", birdie: "Birdie", par: "Par", bogey: "Bogey", worse: "Worse"};
    for (const outcome of data.scoring) {
      const row = element("div", "scoring-frequency");
      const label = `${labels[outcome.result]}: ${outcome.percentage.toFixed(1)}% (${outcome.count} holes)`;
      row.append(element("span", "", label));
      const meter = element("meter");
      meter.min = 0; meter.max = 100; meter.value = outcome.percentage;
      meter.setAttribute("aria-label", label);
      row.append(meter);
      scoring.append(row);
    }
    content.append(scoring);
    const trend = element("section", "panel statistics-panel");
    trend.append(sectionHeading("Scoring trends", "Monthly average to par per round · UTC months · Lower is better."));
    const label = element("label", "", "Round length");
    label.htmlFor = "trend-length";
    const select = element("select");
    select.id = "trend-length";
    for (const row of data.by_length) {
      const option = element("option", "", `${row.hole_count} holes`);
      option.value = row.hole_count;
      select.append(option);
    }
    const chart = element("div");
    function drawTrend() {
      const rows = data.trends.filter(r => r.hole_count === Number(select.value));
      const values = rows.map(r => r.average_score_to_par);
      const low = Math.min(...values), high = Math.max(...values);
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.classList.add("statistics-trend");
      svg.setAttribute("viewBox", "0 0 600 180");
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", `${select.value}-hole monthly scoring trend, oldest to newest. Values from ${low.toFixed(2)} to ${high.toFixed(2)} relative to par. Exact values in the following table.`);
      const points = rows.map((r, i) => [rows.length === 1 ? 300 : 20 + i * 560 / (rows.length - 1), high === low ? 90 : 150 - (r.average_score_to_par - low) * 120 / (high - low)]);
      const line = document.createElementNS(svg.namespaceURI, "polyline");
      line.setAttribute("points", points.map(p => p.join(",")).join(" "));
      svg.append(line);
      points.forEach(([x, y], i) => {
        const dot = document.createElementNS(svg.namespaceURI, "circle");
        dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("r", "4");
        const title = document.createElementNS(svg.namespaceURI, "title");
        title.textContent = `${rows[i].month}: ${relativeScore(rows[i].average_score_to_par)} (${rows[i].rounds} rounds)`;
        dot.append(title); svg.append(dot);
      });
      chart.replaceChildren(element("p", "round-meta", `${rows[0].month} → ${rows.at(-1).month} · Chart range ${relativeScore(low)} to ${relativeScore(high)}. Months without rounds are omitted; spacing is per recorded month.`), svg,
        statisticsTable("Monthly scoring trend", ["Month (UTC)", "Rounds", "Avg to par"], rows.map(r => [r.month, r.rounds, relativeScore(Number(r.average_score_to_par.toFixed(2)))])));
    }
    select.addEventListener("change", drawTrend);
    trend.append(label, select, chart);
    drawTrend();
    content.append(trend);
    const bests = element("section", "panel statistics-panel");
    bests.append(sectionHeading("Personal bests", "Lowest strokes for each course, layout and recorded hole setup. Ties use the most recent round, then round ID."));
    for (const best of data.personal_bests) {
      const entry = element("details", "statistics-best");
      entry.append(element("summary", "", `${best.course_name} · ${best.layout_name} · ${best.hole_count} holes · Par ${best.total_par}: ${best.total_strokes} strokes (${relativeScore(best.score_to_par)})`), element("p", "round-meta", playedDate(best.completed_at)),
        statisticsTable("Personal best hole setup", ["Hole", "Tee", "Basket", "Par", "Distance"], best.holes.map(h => [h.number, h.tee_name, h.basket_name, h.par, h.distance_ft == null ? "Not recorded" : `${h.distance_ft} ft`])));
      bests.append(entry);
    }
    content.append(bests);
    const recent = element("section", "panel statistics-panel");
    recent.append(sectionHeading("Recent performance", "Latest 20 valid linked rounds. Compare like lengths and layouts."), statisticsTable("Recent round performance", ["Completed", "Course / layout", "Holes", "Strokes", "To par"], data.recent_rounds.map(r => [playedDate(r.completed_at), `${r.course_name} / ${r.layout_name}`, r.hole_count, r.total_strokes, relativeScore(r.score_to_par)])));
    content.append(recent);
  } catch (error) {
    if (signal.aborted) return;
    if (error.status === 401) roundSignIn("Statistics");
    else state(view, "Couldn’t load statistics.", "Check your connection and try again.", navigate);
  }
}

function comingSoon(section) {
  const box = element("section", "state");
  box.append(
    element("span", "badge", "COMING SOON"),
    element(
      "h2",
      "",
      section === "players"
        ? "Disc golf is better together."
        : "Every round has a story.",
    ),
    element(
      "p",
      "",
      section === "players"
        ? "A place for your playing community is coming. Player functionality is not available yet."
        : "Round browsing is coming. Round storage and synchronization are not available yet.",
    ),
    link("Explore the course library  →", "#courses", "button primary"),
  );
  view.replaceChildren(box);
}

const pages = {
  dashboard: [
    "Dashboard",
    "YOUR DISC GOLF WORKSPACE",
    "Dashboard",
    "Your course library, connected to your game.",
  ],
  courses: [
    "Courses",
    "FIND YOUR FAIRWAY",
    "The course library.",
    "Familiar favorites. New possibilities. All on your server.",
  ],
  layouts: [
    "Layouts",
    "KNOW THE COURSE",
    "Every hole. Every option.",
    "Explore the playable layouts in your course library.",
  ],
  players: [
    "Players",
    "THE PEOPLE BEHIND THE GAME",
    "Your playing community.",
    "Good company makes a great round.",
  ],
  statistics: ["Statistics", "YOUR GAME IN NUMBERS", "Statistics", "Your performance, from explicitly linked scorecards."],
  rounds: [
    "Round History",
    "ONE THROW AT A TIME",
    "Round History",
    "Your completed rounds. Every player, every hole.",
  ],
};
async function navigate() {
  if (location.hash !== createdCourseHash) courseFeedback.hidden = true;
  requestController?.abort();
  requestController = new AbortController();
  const { signal } = requestController;
  const [path, query = ""] = location.hash.slice(1).split("?");
  const [section = "dashboard", id, ...extra] = (path || "dashboard").split(
    "/",
  );
  const valid =
    Object.hasOwn(pages, section) &&
    !extra.length &&
    (!id || ["courses", "layouts", "rounds"].includes(section));
  const meta = valid
    ? pages[section]
    : [
        "Page not found",
        "OFF THE FAIRWAY",
        "This page is out of bounds.",
        "Use the navigation to find your way back.",
      ];
  document.title = `ChainLink · ${meta[0]}`;
  document.querySelector("#breadcrumb").textContent = meta[0];
  document.querySelector("#eyebrow").textContent = meta[1];
  document.querySelector("#page-title").textContent = meta[2];
  document.querySelector("#page-description").textContent = meta[3];
  for (const item of document.querySelectorAll("[data-page]")) {
    if (valid && item.dataset.page === section)
      item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  if (!initialNavigation) document.querySelector("#main").focus();
  initialNavigation = false;
  view.setAttribute("aria-busy", "true");
  try {
    if (!valid) {
      state(
        view,
        "Page not found",
        "Choose Dashboard, Courses, or Layouts from the navigation.",
      );
    } else if (section === "dashboard") dashboard(signal);
    else if (section === "players") comingSoon(section);
    else if (section === "statistics") await statistics(signal);
    else if (section === "rounds") {
      const requested = Number(new URLSearchParams(query).get("page") || 1);
      const page = Number.isSafeInteger(requested) && requested > 0 && requested <= 1000000 ? requested : 1;
      await roundHistory(id, page, signal);
    }
    else if (id)
      await courseDetail(
        section,
        id,
        signal,
        new URLSearchParams(query).get("layout"),
      );
    else {
      const requested = Number(new URLSearchParams(query).get("page") || 1);
      const page =
        Number.isSafeInteger(requested) && requested > 0 && requested <= 1000000
          ? requested
          : 1;
      await catalog(section, page, signal);
    }
  } catch (error) {
    if (signal.aborted) return;
    state(
      view,
      error.status === 404 ? "Course not found" : "Couldn’t load the catalog.",
      error.status === 404
        ? "This course may no longer be available. Choose Courses to return to the library."
        : "Check your connection and try again. The API or database may be unavailable.",
      navigate,
    );
  } finally {
    if (!signal.aborted) view.setAttribute("aria-busy", "false");
  }
}
document.querySelector(".skip-link").addEventListener("click", (event) => {
  event.preventDefault();
  document.querySelector("#main").focus();
});
window.addEventListener("hashchange", navigate);
window.addEventListener("chainlink-auth-changed", () => {
  if (["#rounds", "#statistics"].includes(location.hash.split(/[/?]/)[0])) navigate();
});
window.addEventListener("pageshow", event => {
  if (event.persisted && ["#rounds", "#statistics"].includes(location.hash.split(/[/?]/)[0])) navigate();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && ["#rounds", "#statistics"].includes(location.hash.split(/[/?]/)[0])) navigate();
});
navigate();

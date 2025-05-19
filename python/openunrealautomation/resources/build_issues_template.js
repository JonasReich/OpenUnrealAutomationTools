// This inline json string will be replaced with the actual json by our Python script that searches for the capitalized variable name
let inline_json = String.raw`INLINE_JSON`;

// ----- GLOBALS -----
let CODE_CONTAINER_TEMPLATE = `<div class="text-nowrap overflow-scroll mx-3 p-3 code-container"><div>`;
let tags_and_labels = FILTER_TAGS_AND_LABELS;
// if true, scopes are drawn nested. legacy feature that will likely not be supported anymore.
const ENABLE_NESTED_SCOPES = false;

var filter = {
    tags: new Set(),
    strings: new Map()
};
var last_goto_lines = new Map();

let all_lines = [];
let all_files = [];

// #TODO Make this automatic -> Collect item values automatically, so we can just call addButtonsForData("Developer")
let all_devs = new Set();
let tag_counts = new Map();

let chart_colors = [
    "#bb4444",
    "#44bb44",
    "#4444bb",
    "#bbbb44",
    "#44bbbb",
    "#bb44bb",

    // -- repeat. not ideal may need to be replaced with actual colors
    "#bb4444",
    "#44bb44",
    "#4444bb",
    "#bbbb44",
    "#44bbbb",
    "#bb44bb",
    //...
    "#bb4444",
    "#44bb44",
    "#4444bb",
    "#bbbb44",
    "#44bbbb",
    "#bb44bb",
    //...
    "#bb4444",
    "#44bb44",
    "#4444bb",
    "#bbbb44",
    "#44bbbb",
    "#bb44bb",
];

let string_var_prefixes = new Map();
string_var_prefixes.set("Developer", "👤");

// map variable name to values to counts
// e.g.
/*
{
    "variable_name" : {
        "value_1" : 10,
        "value_2" : 30
    }
}
*/
let string_vars = new Map();

// ----- GLOBALS -----

const zeroPad = (num, places) => String(num).padStart(places, '0');
function getTagLabel(tag) {
    return tags_and_labels[tag] ?? tag;
}

function goToSource(source_file, line) {
    let new_goto_line = `#source-log-${source_file}-${line}`;
    // show / expand source container
    $(new_goto_line).closest(".source-log-container").show().prev(".btn-expand-source-container").text("Hide source log");

    let last_goto_line = last_goto_lines.has(source_file) ? last_goto_lines.get(source_file) : null;
    if (last_goto_line === null) {
        // do nothing
    } else {
        $(last_goto_line).removeClass("highlight-line");
    }
    $(new_goto_line).addClass("highlight-line");
    window.location = new_goto_line;
    // This does not work properly :/
    // $('html,body').animate({ scrollTop: $(new_goto_line).offset().top }, 500);
    last_goto_lines.set(source_file, new_goto_line);
}

function toggleSourceContainer(button) {
    $(button).next(".source-log-container").toggle();
    let log_visible = $(button).next(".source-log-container").is(":visible");
    $(button).text(log_visible ? "Hide source log" : "Show source log");
}


function increment_map_counter(map, key) {
    if (map.has(key)) {
        map.set(key, map.get(key) + 1);
    } else {
        map.set(key, 1);
    }
}
function increment_tag_count(tag) {
    increment_map_counter(tag_counts, tag);
}

function incrementStringVar(key, value) {
    if (!string_vars.has(key)) {
        string_vars.set(key, new Map());
    }
    let inner_map = string_vars.get(key);
    if (inner_map.has(value)) {
        inner_map.set(value, inner_map.get(value) + 1);
    } else {
        inner_map.set(value, 1);
    }
}


function updateSeverityCSS(element, severity) {
    let is_error = severity == "error";
    let is_warning = severity == "warning";
    let is_severe_warning = severity == "severe_warning";
    let is_message = !is_error && !is_warning && !is_severe_warning;

    element.toggleClass("warning", is_warning);
    element.toggleClass("severe-warning", is_severe_warning);
    element.toggleClass("error", is_error);
    element.toggleClass("message", is_message);
}


function addIssueTable(source_file, scope) {
    // #TODO adjust css classes
    let ref_node = $(`#${source_file}_code-summary`)[0];
    let scope_table = $(`<table class="table table-dark table-sm issue-table"></table>`);
    $(ref_node).empty().append(scope_table);


    let parent_field = $("#issue-grouping-select").val();

    let data = [];
    // no grouping
    if (parent_field.length == 0) {
        // remove pre-gen entries for default grouping
        scope.lines.forEach(line => {
            if (line.is_group || line.is_scope) {
                return;
            }
            data.push(line);
        });
    }
    else if (parent_field == "scope") {
        // default grouping -> this already contains group entries from python
        data = scope.lines;
    } else {
        // custom grouping: group by unique column values.
        // for this mode, we use a "pid" key.
        // using the actual column field we want to group by for some reason leads to issues (infinite recursion).
        let unique_keys = new Set();
        let key_counts = new Map();
        let filtered_lines = [];
        scope.lines.forEach(line => {
            let parent_field_value = line[parent_field];
            if ((parent_field_value === undefined) == false) {
                if (typeof parent_field_value == "string") {
                    if (parent_field_value.trim().length > 0) {
                        filtered_lines.push(line);
                        unique_keys.add(parent_field_value);
                        increment_map_counter(key_counts, parent_field_value);
                    }
                } else {
                    // column valud could be array, etc
                    // no idea how to deal with this
                    console.warn(`unsupported group column type: ${typeof parent_field_value}`)
                }
            }
        });
        let key_lookup = new Map();
        let i = -1;
        unique_keys.forEach(key => {
            i--;
            let key_line = {
                id: i,
                line: `${key} (${key_counts.get(key)})`,
                is_group: true,
            };
            key_lookup[key] = i;
            key_line.pid = 0;
            data.push(key_line);
        });
        filtered_lines.forEach(line => {
            line.pid = key_lookup[line[parent_field]];
            data.push(line);
        });
        parent_field = "pid";
    }

    $(ref_node).find('table').bootstrapTable({
        data: data,
        idField: 'id',
        showColumns: true,
        columns: [
            /*{
                // synthetic column for tree collapse (tc)
                field: 'tc',
                width: 100,
                formatter: function () { return "" },
            },*/
            {
                field: 'id',
                title: 'ID/Line Number',
                sortable: true,
                width: 100,
                formatter: function (value) { return Number.isNaN(Number(value)) || Number(value) < 0 ? "" : `<button class="btn btn-secondary badge" onclick="goToSource('${source_file}', ${value})">${value}</button>`; }
            },
            {
                field: 'line',
                title: 'Text',
                // width -> the only flexible width column
                class: 'line-text',
                sortable: true
            },
            {
                field: 'time',
                title: 'Timestamp',
                width: 100
            },
            {
                field: 'severity',
                title: 'Status/Severity',
                sortable: true,
                width: 100
            },
            {
                field: 'tags',
                title: 'Tags',
                sortable: true,
                width: 100
            },
            {
                field: 'developer',
                title: 'Developer',
                sortable: true,
                width: 100
            },
            {
                field: 'asset',
                title: 'Asset',
                sortable: true,
                width: 400
            },
            {
                field: 'occurences',
                title: 'Occurences',
                sortable: true,
                width: 100
            }

        ],
        treeShowField: 'id',
        rowStyle: function (row, index) {
            const row_header_class = (row.is_scope) ? " row-scope" : (row.is_group) ? " row-group" : "";
            return { classes: row.severity + row_header_class };
        },

        // parentIdField: 'pid',
        parentIdField: parent_field,

        onPostBody() {
            $table = $(ref_node).find('table');
            $table.treegrid({
                treeColumn: 0,
                onChange() {
                    $table.bootstrapTable('resetView')
                }
            })
            if (parent_field.length > 0) {
                $(".row-group").treegrid("collapse")
            }
        }
    });
}

let json_obj = JSON.parse(inline_json);
console.log(json_obj);
rebuildIssueTables();
$("#issue-grouping-select").change(function () {
    rebuildIssueTables();
})

function rebuildIssueTables() {
    all_files = [];
    for (const [source_file, issue_scope] of Object.entries(json_obj)) {
        all_files.push(source_file);
        if (issue_scope.lines.length > 0) {
            addIssueTable(source_file, issue_scope);
        }
    }
}

function updateScopeCounters() {
    $(".issue-scope").each(function () {
        num_children = 0;
        num_active_children = 0;
        $(this).find("code").each(function () {
            num_children++;
            if ($(this).css("display") != "none")
                num_active_children++;
        })

        summary = $(this).find(".issue-scope-summary");
        json_data = $(this).data("json");

        summary.html("<span class='px-2'>" + json_data.name + ` (${num_active_children}/${num_children})` + "</span>");
        $(this).toggle(num_active_children > 0);

        for (let tag_idx = 0; tag_idx < json_data.tags.length; tag_idx++) {
            let tag = json_data.tags[tag_idx];
            $(summary).append(createTagButton(tag, false));
        }
    })
    $(".line-group").each(function () {
        num_children = 0;
        num_active_children = 0;
        $(this).find("code").each(function () {
            num_children++;
            if ($(this).css("display") != "none")
                num_active_children++;
        })

        summary = $(this).find(".line-group-summary");
        line_group_name = $(this).data("name");

        summary.html("<span class='px-2'>" + line_group_name + ` (${num_active_children}/${num_children})` + "</span>");
        $(this).toggle(num_active_children > 0);
    })
}
updateScopeCounters();

function resetFilter() {
    filter.tags.clear();
    filter.strings.clear();

    $(".code-summary code").show();
    // Reset all filter buttons
    $(".filter-btn").toggleClass("btn-primary", false);
    $(".filter-btn").toggleClass("btn-secondary", true);
}

function applyFilter() {
    $(".code-summary code").each(function () {
        let tags = $(this).data("json")["tags"];
        let has_all_tags = true;
        for (const filter_tag of filter.tags.keys()) {
            if (tags.includes(filter_tag) == false) {
                has_all_tags = false;
            }
        }
        if (!has_all_tags) {
            $(this).toggle(false);
            return;
        }
        let has_all_strings = true;
        for (const [string_var, string_value] of filter.strings.entries()) {
            let item_string_value = $(this).data("json").strings[string_var];
            if (item_string_value != string_value) {
                has_all_strings = false;
            }
        }
        $(this).toggle(has_all_strings);
    });

    updateScopeCounters();
}

let show_all_button = $("#show-all-btn");
$(show_all_button).click(function () {
    resetFilter();

    // Set show all button to primary (blue)
    $("#show-all-btn").toggleClass("btn-primary", true);
    $("#show-all-btn").toggleClass("btn-secondary", false);

    updateScopeCounters();
})
$("#filter-btns").append(show_all_button);

function filterTags(tag) {
    let filter_now = filter.tags.has(tag) == false;
    if (filter_now) {
        filter.tags.add(tag);
    } else {
        filter.tags.delete(tag);
    }

    $("#show-all-btn").toggleClass("btn-primary", false);
    $("#show-all-btn").toggleClass("btn-secondary", true);

    applyFilter();

    $(".tag-btn").each(function () {
        let btn_tag = $(this).data("tag");
        if (btn_tag == tag) {
            $(this).toggleClass("btn-primary", filter_now);
            $(this).toggleClass("btn-secondary", !filter_now);
        }
    });
}

function createTagButton(tag, add_count) {
    let tag_count = tag_counts.has(tag) ? tag_counts.get(tag) : 0;
    let count_suffix = add_count ? ` (${tag_count})` : "";
    let tag_button = $(`<button class="btn badge rounded-pill btn-secondary filter-btn tag-btn">${getTagLabel(tag)}${count_suffix}</button>`);
    tag_button.data("tag", tag);
    $(tag_button).click(function () { filterTags(tag) });
    return tag_button
}

// Add buttons
for (let [tag, label] of Object.entries(tags_and_labels)) {
    $("#filter-btns").append(createTagButton(tag, true));
}

$("#filter-btns").append($("<div class='m-2'/>"));

function filterStringData(string_var, string_value) {
    let filter_now = true;
    if (filter.strings.has(string_var)) {
        if (filter.strings.get(string_var) == string_value) {
            filter.strings.delete(string_var);
            filter_now = false;
        }
    }
    if (filter_now) {
        filter.strings.set(string_var, string_value);
    }

    $("#show-all-btn").toggleClass("btn-primary", false);
    $("#show-all-btn").toggleClass("btn-secondary", true);

    $(".string-filter-btn").each(function () {
        let item = $(this).data(string_var);
        if (item == string_value) {
            $(this).toggleClass("btn-primary", filter_now);
            $(this).toggleClass("btn-secondary", !filter_now);
        } else {
            // developer buttons are mutually exclusive
            $(this).toggleClass("btn-primary", false);
            $(this).toggleClass("btn-secondary", true);
        }
    });
    applyFilter();
}

function createStringVarFilterButton(string_var, string_value, display_count) {
    let value_count = string_vars.get(string_var).get(string_value);
    let button_prefix = string_var_prefixes.has(string_var) ? string_var_prefixes.get(string_var) : "";
    let count_str_suffix = display_count ? ` (${value_count})` : "";
    let button = $(`<button class="btn btn-sm btn-secondary filter-btn string-filter-btn badge rounded">${button_prefix} ${string_value}${count_str_suffix}</button>`);
    button.data(string_var, string_value);
    $(button).click(function () { filterStringData(string_var, string_value) });
    return button;
}

function addFilterButtonForStringVar(string_var, string_var_items) {
    string_var_items.forEach(function (item) {
        if (item == "") return;
        let button = createStringVarFilterButton(string_var, item, true);
        $("#filter-btns").append(button);
    })
}

addFilterButtonForStringVar("Developer", all_devs);

//---------------------------
// STATS

function getStatsRoot() {
    return $("#stats-chart-root")[0];
}

// Craete a chart canvas context
function createChartJsContext() {
    let canvasRoot = getStatsRoot();
    var canvasTemplate = '<canvas class="stats-chart p-2 mb-2 bg-dark"></canvas>';
    let canvas = $(canvasTemplate).appendTo(canvasRoot)[0];
    $(canvas).css("display", "inline-block");
    return canvas.getContext('2d');
}

function createIssuesPerTagChart() {
    let labels = [];
    let error_counts = [];
    let warning_counts = [];
    let severe_warning_counts = [];
    let message_counts = [];

    let error_counts_total = [];
    let warning_counts_total = [];
    let severe_warning_counts_total = [];
    let message_counts_total = [];

    // #TODO instead of counting occurences manually, the json export should contain tag data incl. unique tag occurences + total tag occurences
    tag_counts.forEach(function (count, tag) {
        labels.push(getTagLabel(tag));
        let error_count = 0;
        let warning_count = 0;
        let severe_warning_count = 0;
        let message_count = 0;
        let error_count_total = 0;
        let warning_count_total = 0;
        let severe_warning_count_total = 0;
        let message_count_total = 0;
        count = $(".code-summary code").each(function () {
            if ($(this).data("json").tags.includes(tag) == false) {
                return;
            }
            if ($(this).data("json").severity == "error") {
                error_count++;
                error_count_total += $(this).data("json").occurences;
            } else if ($(this).data("json").severity == "warning") {
                warning_count++;
                warning_count_total += $(this).data("json").occurences;
            } else if ($(this).data("json").severity == "severe_warning") {
                severe_warning_count++;
                severe_warning_count_total += $(this).data("json").occurences;
            } else {
                message_count++;
                message_count_total += $(this).data("json").occurences;
            }
        })
        error_counts.push(error_count);
        warning_counts.push(warning_count);
        severe_warning_counts.push(severe_warning_count);
        message_counts.push(message_count);
        error_counts_total.push(error_count_total);
        warning_counts_total.push(warning_count_total);
        severe_warning_counts_total.push(severe_warning_count_total);
        message_counts_total.push(message_count_total);
    })

    function createIssueCountChart(title, error_counts_var, warning_counts_var, severe_warning_counts_var, message_counts_var) {
        new Chart(createChartJsContext(), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    { label: "Errors", data: error_counts_var, backgroundColor: "#bb4444", color: "#bb4444" },
                    { label: "Warnigns", data: warning_counts_var, backgroundColor: "#bbbb44", color: "#bbbb44" },
                    { label: "Severe Warnigns", data: severe_warning_counts_var, backgroundColor: "#e9a00f", color: "#e9a00f" },
                    { label: "Messages", data: message_counts_var, backgroundColor: "#aaaaaa", color: "#aaaaaa" }
                ]
            },
            options: {
                color: "white",
                backgroundColor: "transparent",
                plugins: {
                    title: { display: true, text: title }
                }
            }
        });
    }

    createIssueCountChart("Issues per Tag (Unique)", error_counts, warning_counts, severe_warning_counts, message_counts);
    createIssueCountChart("Issues per Tag (Total)", error_counts_total, warning_counts_total, severe_warning_counts_total, message_counts_total);
}
createIssuesPerTagChart()

const ChartPreset = {
    BAR: "bar",
    BAR_HORIZONTAL: "barh",
    LINE: "line",
    PIE: "pie"
};
function getChartTypeStr(preset) {
    let type = "bar";
    switch (preset) {
        case ChartPreset.BAR:
        case ChartPreset.BAR_HORIZONTAL:
            type = "bar"
            break
        case ChartPreset.LINE:
            type = "line"
            break
        case ChartPreset.PIE:
            type = "pie"
            break
    }
    return type;
}

function createNumericsChart(preset, chart_title, datasets, item_labels) {
    let indexAxis = (preset == ChartPreset.BAR_HORIZONTAL ? 'y' : 'x');
    new Chart(createChartJsContext(), {
        type: getChartTypeStr(preset),
        data: {
            labels: Array.from(item_labels),
            datasets: datasets
        },
        options: {
            color: "white",
            backgroundColor: "transparent",
            indexAxis: indexAxis,
            plugins: {
                title: {
                    display: true,
                    text: chart_title
                }
            }
        }
    });
}

// Create a dynamic chart based on numerics data
// item_key_variable is the string variable name to use as label for data points
// stats are the individual numerics -> 1 data set per stat
// lables are display names for the data sets
function createNumericsChartFromJsonData(preset, chart_title, item_key_variable, stats, labels, file) {
    let datasets = [];
    let item_labels = [];
    let has_min_1_datapoint = false;

    for (let i = 0; i < stats.length; i++) {
        const stat = stats[i];
        let data = [];
        let code_idx = 0;
        all_lines.forEach(function (json) {
            if (json.source_file != file) {
                return;
            }

            let datapoint_key = json.strings[item_key_variable];
            if (datapoint_key === undefined) {
                return;
            }

            const data_point = json.numerics[stat];
            item_labels.length = Math.max(item_labels.length, code_idx + 1);
            item_labels[code_idx] = datapoint_key;
            data.push(data_point);
            code_idx++;
            has_min_1_datapoint = true;
        })
        const color = preset == ChartPreset.PIE ? chart_colors : chart_colors[i];
        const label = labels[i];
        datasets.push({
            label: label,
            data: data,
            backgroundColor: color,
            color: color,
            borderColor: color
        });
    }

    if (has_min_1_datapoint == false) {
        // This made more sense when we had a single log file. With multiple files, not all of which contain cook steps, this warning is misleading / useless.
        // $(getStatsRoot()).append(`<div><i>No datapoints for '${chart_title}' chart</i></div>`);
        return;
    }

    createNumericsChart(preset, chart_title, datasets, item_labels);
}
let ddc_stats = ["DDC_TotalTime", "DDC_GameThreadTime", "DDC_AssetNum", "DDC_MB"];
let ddc_labels = ["Total Time", "Game Thread Time", "Asset Number", "MB"];
all_files.forEach(function (file) {
    createNumericsChartFromJsonData(ChartPreset.LINE, "DDC Resource Stats " + file, "DDC_Key", ddc_stats, ddc_labels, file);
});
all_files.forEach(function (file) {
    // createNumericsChartFromJsonData(ChartPreset.PIE, "UAT Command Times " + file, "UAT_Command", ["Duration"], ["Duration"], file);
});

function createCsvChart(preset, chart_title, csv_str) {
    let datasets = [];
    let item_labels = [];

    let csv_rows = csv_str.split('\n');
    let csv_array = csv_rows.map(col => col.split(','));
    let csv_header_row = csv_rows[0].split(',');

    let num_cols = csv_header_row.length;
    let num_rows = csv_rows.length;

    for (let col_idx = 0; col_idx < num_cols; col_idx++) {
        let data = [];
        for (let row_idx = 1; row_idx < num_rows; row_idx++) {
            let datapoint = csv_array[row_idx][col_idx];
            data.push(datapoint);
        }

        if (col_idx == 0) {
            item_labels = data;
            continue;
        }

        let data_label = csv_array[0][col_idx];
        const color = preset == ChartPreset.PIE ? chart_colors : chart_colors[col_idx];
        datasets.push({
            label: data_label,
            data: data,
            backgroundColor: color,
            color: color,
            borderColor: color
        });
    }

    createNumericsChart(preset, chart_title, datasets, item_labels);
}

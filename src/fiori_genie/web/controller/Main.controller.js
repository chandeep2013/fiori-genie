sap.ui.define(
    [
        "sap/ui/core/mvc/Controller",
        "sap/m/MessageToast",
        "sap/m/MessageBox"
    ],
    function (Controller, MessageToast, MessageBox) {
        "use strict";

        var EDITOR_TYPES = {
            cds: "sql",
            json: "json",
            js: "javascript",
            ts: "javascript",
            xml: "xml",
            html: "html",
            yaml: "yaml",
            yml: "yaml",
            csv: "plain_text",
            properties: "properties",
            md: "markdown"
        };

        return Controller.extend("fiorigenie.controller.Main", {
            onInit: function () {
                this._model = this.getOwnerComponent().getModel("app");
                this._checkProvider();
            },

            _checkProvider: function () {
                var model = this._model;

                fetch("api/status")
                    .then(function (response) {
                        return response.json();
                    })
                    .then(function (status) {
                        model.setProperty("/providerReady", status.providerReady);
                        model.setProperty(
                            "/providerLabel",
                            status.providerReady
                                ? status.provider + " · " + status.model
                                : "No LLM provider configured"
                        );
                        if (!status.providerReady) {
                            model.setProperty("/message", status.detail);
                            model.setProperty("/messageType", "Warning");
                        }
                    })
                    .catch(function () {
                        model.setProperty("/providerLabel", "Backend unreachable");
                    });
            },

            onLoadSample: function () {
                var model = this._model;

                fetch("api/sample-spec")
                    .then(function (response) {
                        return response.json();
                    })
                    .then(function (payload) {
                        if (payload.spec) {
                            model.setProperty("/spec", payload.spec);
                        } else {
                            MessageToast.show("No sample spec found on the server");
                        }
                    });
            },

            onClear: function () {
                this._model.setProperty("/spec", "");
                this._model.setProperty("/projectName", "");
                this._reset();
            },

            _reset: function () {
                var model = this._model;
                model.setProperty("/hasResult", false);
                model.setProperty("/runId", null);
                model.setProperty("/entities", []);
                model.setProperty("/services", []);
                model.setProperty("/files", []);
                model.setProperty("/log", []);
                model.setProperty("/attemptTrace", []);
                model.setProperty("/selectedFile", null);
                model.setProperty("/selectedContent", "");
                model.setProperty("/message", null);
            },

            onGenerate: function () {
                var model = this._model;
                var that = this;

                this._reset();
                model.setProperty("/busy", true);

                fetch("api/generate", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        spec: model.getProperty("/spec"),
                        projectName: model.getProperty("/projectName") || null,
                        attempts: model.getProperty("/attempts")
                    })
                })
                    .then(function (response) {
                        return response.json().then(function (body) {
                            return { ok: response.ok, body: body };
                        });
                    })
                    .then(function (result) {
                        model.setProperty("/busy", false);

                        if (!result.ok) {
                            that._fail(result.body.detail || "Request failed");
                            return;
                        }
                        that._applyResult(result.body);
                    })
                    .catch(function (error) {
                        model.setProperty("/busy", false);
                        that._fail(String(error));
                    });
            },

            _fail: function (message) {
                this._model.setProperty("/message", message);
                this._model.setProperty("/messageType", "Error");
            },

            _applyResult: function (payload) {
                var model = this._model;

                model.setProperty(
                    "/log",
                    (payload.log || []).map(function (text) {
                        return { text: text };
                    })
                );
                model.setProperty(
                    "/attemptTrace",
                    (payload.attempts || []).map(function (attempt) {
                        return {
                            number: attempt.number,
                            stage: attempt.stage,
                            summary:
                                attempt.errors && attempt.errors.length
                                    ? attempt.errors.slice(0, 3).join(" · ")
                                    : "accepted"
                        };
                    })
                );

                if (!payload.ok) {
                    model.setProperty("/hasResult", true);
                    this._fail(
                        "Generation failed after " +
                            (payload.attempts || []).length +
                            " attempt(s). See the run log."
                    );
                    return;
                }

                model.setProperty("/runId", payload.runId);
                model.setProperty("/files", payload.files || []);
                model.setProperty("/entities", this._toDesign(payload.model));
                model.setProperty("/services", this._toServices(payload.model));
                model.setProperty("/hasResult", true);
                model.setProperty(
                    "/message",
                    "Generated " +
                        (payload.files || []).length +
                        " files. The CDS compiler accepted the model."
                );
                model.setProperty("/messageType", "Success");

                var files = payload.files || [];
                var schema = files.filter(function (file) {
                    return file.path.indexOf("schema.cds") !== -1;
                })[0];
                if (schema) {
                    this._showFile(schema);
                }
            },

            _toDesign: function (model) {
                if (!model || !model.entities) {
                    return [];
                }

                return model.entities.map(function (entity) {
                    var aspects = [];
                    if (entity.useCuid !== false) {
                        aspects.push("cuid");
                    }
                    if (entity.useManaged !== false) {
                        aspects.push("managed");
                    }

                    var members = (entity.fields || []).map(function (field) {
                        var flags = [];
                        if (field.key) {
                            flags.push("key");
                        }
                        if (field.notNull) {
                            flags.push("not null");
                        }
                        if (field.enum) {
                            flags.push("enum(" + Object.keys(field.enum).length + ")");
                        }
                        if (field.default) {
                            flags.push("default " + field.default);
                        }

                        var type = field.type;
                        if (field.length) {
                            type += "(" + field.length + ")";
                        }
                        if (field.precision) {
                            type += "(" + field.precision + "," + field.scale + ")";
                        }

                        return {
                            name: field.name,
                            type: type,
                            label: field.label || "",
                            flags: flags.join(", ")
                        };
                    });

                    (entity.relations || []).forEach(function (relation) {
                        var kind =
                            relation.kind === "composition" ? "Composition" : "Association";
                        var arity = relation.cardinality === "to-many" ? "many " : "";
                        members.push({
                            name: relation.name,
                            type: kind + " → " + arity + relation.target,
                            label: relation.label || "",
                            flags: relation.backlink ? "on " + relation.backlink : ""
                        });
                    });

                    return {
                        name: entity.name,
                        doc: entity.doc || "",
                        aspects: aspects.join(", "),
                        members: members
                    };
                });
            },

            _toServices: function (model) {
                if (!model || !model.services) {
                    return [];
                }

                return model.services.map(function (service) {
                    var exposed = (service.entities || []).map(function (entry) {
                        var suffix = [];
                        if (entry.draftEnabled) {
                            suffix.push("draft");
                        }
                        if (entry.readonly) {
                            suffix.push("readonly");
                        }
                        return (
                            entry.entity +
                            (suffix.length ? " (" + suffix.join(", ") + ")" : "")
                        );
                    });

                    return {
                        name: service.name,
                        detail: exposed.join(" · ")
                    };
                });
            },

            onFileSelect: function (event) {
                var item = event.getParameter("listItem");
                if (!item) {
                    return;
                }
                this._showFile(item.getBindingContext("app").getObject());
            },

            _showFile: function (file) {
                var extension = (file.path.split(".").pop() || "").toLowerCase();

                this._model.setProperty("/selectedFile", file.path);
                this._model.setProperty(
                    "/selectedContent",
                    file.content === null || file.content === undefined
                        ? "(not previewable)"
                        : file.content
                );
                this._model.setProperty(
                    "/selectedType",
                    EDITOR_TYPES[extension] || "plain_text"
                );
            },

            onCopy: function () {
                var content = this._model.getProperty("/selectedContent");

                if (navigator.clipboard) {
                    navigator.clipboard.writeText(content).then(function () {
                        MessageToast.show("Copied");
                    });
                } else {
                    MessageBox.information("Clipboard is unavailable in this context.");
                }
            },

            onDownload: function () {
                var runId = this._model.getProperty("/runId");
                if (runId) {
                    window.location.href = "api/download/" + runId;
                }
            }
        });
    }
);

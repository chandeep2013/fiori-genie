sap.ui.define(
    ["sap/ui/core/UIComponent", "sap/ui/model/json/JSONModel"],
    function (UIComponent, JSONModel) {
        "use strict";

        return UIComponent.extend("fiorigenie.Component", {
            metadata: {
                manifest: "json"
            },

            init: function () {
                UIComponent.prototype.init.apply(this, arguments);

                this.setModel(
                    new JSONModel({
                        spec: "",
                        projectName: "",
                        attempts: 3,
                        busy: false,
                        busyText: "",
                        providerReady: false,
                        providerLabel: "checking...",
                        hasResult: false,
                        runId: null,
                        outputPath: null,
                        entities: [],
                        services: [],
                        files: [],
                        log: [],
                        attemptTrace: [],
                        selectedFile: null,
                        selectedContent: "",
                        selectedType: "javascript",
                        message: null,
                        messageType: "None"
                    }),
                    "app"
                );
            }
        });
    }
);

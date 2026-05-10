import { configureStore } from "@reduxjs/toolkit";
import createSagaMiddleware from "redux-saga";
import projectReducer from "./project-slice";
import streamsReducer from "./streams-slice";
import { streamsSaga } from "./streams-saga";

export const makeStore = () => {
    const sagaMiddleware = createSagaMiddleware();

    const store = configureStore({
        reducer: {
            project: projectReducer,
            streams: streamsReducer,
        },
        middleware: (getDefaultMiddleware) =>
            getDefaultMiddleware({
                serializableCheck: {
                    ignoredActions: ["streams/streamEventReceived"],
                    ignoredPaths: ["streams.streams"],
                },
            }).concat(sagaMiddleware),
    });

    sagaMiddleware.run(streamsSaga);

    return store;
};

export type AppStore = ReturnType<typeof makeStore>;
export type RootState = ReturnType<AppStore["getState"]>;
export type AppDispatch = AppStore["dispatch"];

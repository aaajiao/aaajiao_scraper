import Foundation

runAppTests(
    openAIModelSettingsTests()
        + appUtilitiesTests()
        + importerDTOTests()
        + helperClientErrorTests()
        + helperProcessTests()
)

await runAsyncAppTests(appModelTests())
